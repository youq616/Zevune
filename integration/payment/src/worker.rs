//! Private framed pipe protocol. No wallet or proving requests are accepted.
use crate::chain::{decode_tx_hex, Block, MAX_EXPORT};
use crate::store::Store;
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{Read, Write};
const MAX_REQUEST: usize = 600_000;

#[derive(Deserialize)]
#[serde(tag = "op", deny_unknown_fields)]
enum Request {
    #[serde(rename = "info")]
    Info { id: u64 },
    #[serde(rename = "export")]
    Export { id: u64 },
    #[serde(rename = "check")]
    Check { id: u64, tx: String },
    #[serde(rename = "preview")]
    Preview { id: u64, block: Block },
    #[serde(rename = "stage")]
    Stage { id: u64, block: Block },
    #[serde(rename = "commit")]
    Commit { id: u64, height: u64, hash: String },
}
#[derive(Serialize)]
struct Response {
    id: u64,
    ok: bool,
    error: Option<&'static str>,
    data: Value,
}
fn id(request: &Request) -> u64 {
    match request {
        Request::Info { id }
        | Request::Export { id }
        | Request::Check { id, .. }
        | Request::Preview { id, .. }
        | Request::Stage { id, .. }
        | Request::Commit { id, .. } => *id,
    }
}
fn handle(store: &mut Store, request: Request) -> Result<Value> {
    match request {
        Request::Info { .. } => Ok(json!(store.ledger.summary())),
        Request::Export { .. } => Ok(json!(store.ledger.export())),
        Request::Check { tx, .. } => {
            let at = store.ledger.height.checked_add(1).ok_or(Error::Limit)?;
            store
                .ledger
                .check(&decode_tx_hex(&tx)?, at, &store.verifier)?;
            Ok(json!({"accepted":true,"finality":false}))
        }
        Request::Preview { block, .. } => Ok(json!(store.preview(&block)?)),
        Request::Stage { block, .. } => Ok(json!(store.stage(block)?)),
        Request::Commit { height, hash, .. } => Ok(json!(store.commit(height, &hash)?)),
    }
}
pub fn serve(mut store: Store, mut input: impl Read, mut output: impl Write) -> Result<()> {
    loop {
        let mut length = [0; 4];
        // A closed owner pipe terminates the worker and releases its file lock.
        match input.read_exact(&mut length[..1]) {
            Ok(()) => (),
            Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => return Ok(()),
            Err(_) => return Err(Error::Storage),
        }
        input
            .read_exact(&mut length[1..])
            .map_err(|_| Error::Encoding)?;
        let n = u32::from_be_bytes(length) as usize;
        if n == 0 || n > MAX_REQUEST {
            return Err(Error::Limit);
        }
        let mut bytes = vec![0; n];
        input.read_exact(&mut bytes).map_err(|_| Error::Encoding)?;
        let request: Request = serde_json::from_slice(&bytes).map_err(|_| Error::Encoding)?;
        let seq = id(&request);
        let result = handle(&mut store, request);
        let fatal = matches!(result, Err(Error::Storage));
        let response = match result {
            Ok(data) => Response {
                id: seq,
                ok: true,
                error: None,
                data,
            },
            Err(_) => Response {
                id: seq,
                ok: false,
                error: Some(if fatal {
                    "storage_unavailable"
                } else {
                    "rejected"
                }),
                data: Value::Null,
            },
        };
        let bytes = serde_json::to_vec(&response).map_err(|_| Error::Encoding)?;
        if bytes.len() > MAX_EXPORT {
            return Err(Error::Limit);
        }
        output
            .write_all(&(bytes.len() as u32).to_be_bytes())
            .and_then(|_| output.write_all(&bytes))
            .and_then(|_| output.flush())
            .map_err(|_| Error::Storage)?;
        if fatal {
            return Err(Error::Storage);
        }
    }
}
