//! Private child-process protocol. No listener, wallet RPC or arbitrary command.
//! Success reports stateless cryptographic authorization, never ledger validity.
use crate::wire::{payload_digest, AuthorizationVerifier, MAX_ENVELOPE_SIZE};
use sha2::{Digest, Sha256};
use std::io::{self, Read, Write};

pub const MAX_FRAME: usize = MAX_ENVELOPE_SIZE + 20;
pub const HELLO_MAGIC: &[u8; 8] = b"ZVOH0001";
pub const REQUEST_MAGIC: &[u8; 8] = b"ZVOQ0001";
pub const RESPONSE_MAGIC: &[u8; 8] = b"ZVOS0001";

pub fn fingerprint() -> [u8; 32] {
    Sha256::digest(b"ZEVUNE-BRIDGE-V1\0orchard=0.15.5\0circuit=FixedPostNu6_2\0network=zevune-orchard-lab-1\0wire=ZVORLAB1\0").into()
}
fn protocol_error() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "invalid local worker frame")
}

pub fn read_frame<R: Read>(reader: &mut R, limit: usize) -> io::Result<Option<Vec<u8>>> {
    if limit == 0 || limit > MAX_FRAME {
        return Err(protocol_error());
    }
    let mut prefix = [0u8; 4];
    loop {
        match reader.read(&mut prefix[..1]) {
            Ok(0) => return Ok(None),
            Ok(_) => break,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    reader.read_exact(&mut prefix[1..])?;
    let len = u32::from_be_bytes(prefix) as usize;
    if len == 0 || len > limit {
        return Err(protocol_error());
    }
    let mut body = vec![0; len];
    reader.read_exact(&mut body)?;
    Ok(Some(body))
}
pub fn write_frame<W: Write>(writer: &mut W, body: &[u8]) -> io::Result<()> {
    if body.is_empty() || body.len() > MAX_FRAME {
        return Err(protocol_error());
    }
    writer.write_all(&(body.len() as u32).to_be_bytes())?;
    writer.write_all(body)?;
    writer.flush()
}

/// A monotonically numbered, fixed-operation session. Malformed framing is fatal;
/// a well-framed invalid transaction is a normal rejection. No request can
/// choose a different circuit, load keys, access files, or mutate a ledger.
pub fn serve<R: Read, W: Write>(reader: &mut R, writer: &mut W) -> io::Result<()> {
    let verifier = AuthorizationVerifier::new();
    let mut hello = Vec::from(*HELLO_MAGIC);
    hello.extend_from_slice(&fingerprint());
    write_frame(writer, &hello)?;
    let mut last_id = 0u64;
    while let Some(request) = read_frame(reader, MAX_FRAME)? {
        if request.len() < 20 || request.get(..8) != Some(REQUEST_MAGIC.as_slice()) {
            return Err(protocol_error());
        }
        let id = u64::from_be_bytes(request[8..16].try_into().map_err(|_| protocol_error())?);
        let len =
            u32::from_be_bytes(request[16..20].try_into().map_err(|_| protocol_error())?) as usize;
        if id == 0 || id <= last_id || len > MAX_ENVELOPE_SIZE || len != request.len() - 20 {
            return Err(protocol_error());
        }
        last_id = id;
        let raw = &request[20..];
        let digest = payload_digest(raw);
        let status = if verifier.verify(raw).is_ok() { 0 } else { 1 };
        let mut response = Vec::with_capacity(49);
        response.extend_from_slice(RESPONSE_MAGIC);
        response.extend_from_slice(&id.to_be_bytes());
        response.push(status);
        response.extend_from_slice(&digest);
        write_frame(writer, &response)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn fingerprint_matches_go_vector() {
        assert_eq!(
            fingerprint(),
            [
                0x30, 0x12, 0xf3, 0xed, 0xe4, 0x9b, 0x55, 0x1c, 0xd1, 0x31, 0xe8, 0xba, 0xe0, 0x49,
                0xd6, 0x6f, 0x37, 0x74, 0x0a, 0x5c, 0xb0, 0x84, 0x05, 0x23, 0x94, 0x92, 0x9f, 0x9b,
                0x23, 0xe4, 0x3a, 0xb6
            ]
        );
    }
    #[test]
    fn bounded_frame_rejections() {
        assert!(read_frame(&mut Cursor::new([255; 4]), MAX_FRAME).is_err());
        assert!(read_frame(&mut Cursor::new([0; 4]), MAX_FRAME).is_err());
        assert!(read_frame(&mut Cursor::new([0, 0, 0, 4, 1]), MAX_FRAME).is_err());
        assert!(read_frame(&mut Cursor::new([0]), MAX_FRAME).is_err());
        assert!(read_frame(&mut Cursor::new(Vec::<u8>::new()), MAX_FRAME)
            .unwrap()
            .is_none());
    }
    #[test]
    fn frame_roundtrip() {
        let mut bytes = Vec::new();
        write_frame(&mut bytes, b"public").unwrap();
        assert_eq!(
            read_frame(&mut Cursor::new(bytes), MAX_FRAME)
                .unwrap()
                .unwrap(),
            b"public"
        );
    }
}
