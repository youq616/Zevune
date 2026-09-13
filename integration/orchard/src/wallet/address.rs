//! Experimental local address presentation; checksums are NOT authentication.
//! LAB2 recipients carry the exact pinned payment domain. LAB1 is explicitly
//! unbound. Neither format identifies a person or proves control of a receiver.
use orchard::Address;
use sha2::{Digest, Sha256};
use std::fmt;

const LEGACY_DOMAIN: &[u8] = b"ZEVUNE-LOCAL-ADDRESS\0\x01";
const BOUND_DOMAIN: &[u8] = b"ZEVUNE-LOCAL-ADDRESS\0\x02";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AddressError {
    Encoding,
    Network,
}
impl fmt::Display for AddressError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "local recipient rejected: {self:?}")
    }
}
impl std::error::Error for AddressError {}

/// Public receiver plus declared payment domain, not an authenticated payee.
/// The raw receiver is returned only after an explicit expected-domain check.
#[derive(Clone, Copy, Eq, PartialEq)]
pub struct Recipient {
    address: Address,
    domain: Option<[u8; 32]>,
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn unhex<const N: usize>(text: &str) -> Result<[u8; N], AddressError> {
    if text.len() != 2 * N
        || !text
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(AddressError::Encoding);
    }
    let mut out = [0; N];
    for (index, byte) in out.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[2 * index..2 * index + 2], 16)
            .map_err(|_| AddressError::Encoding)?;
    }
    Ok(out)
}
impl Recipient {
    pub fn new(address: Address, domain: Option<[u8; 32]>) -> Result<Self, AddressError> {
        if domain == Some([0; 32]) {
            return Err(AddressError::Network);
        }
        Ok(Self { address, domain })
    }
    pub fn encode(&self) -> String {
        let raw = self.address.to_raw_address_bytes();
        let mut digest = Sha256::new();
        if let Some(domain) = self.domain {
            digest.update(BOUND_DOMAIN);
            digest.update(domain);
            digest.update(raw);
            format!(
                "zvlab2:{}:{}:{}",
                hex(&domain),
                hex(&raw),
                hex(&digest.finalize()[..8])
            )
        } else {
            digest.update(LEGACY_DOMAIN);
            digest.update(raw);
            format!("zvlab:{}:{}", hex(&raw), hex(&digest.finalize()[..4]))
        }
    }
    pub fn decode(text: &str) -> Result<Self, AddressError> {
        // Exact byte bounds before splitting, allocation or curve parsing.
        if !matches!(text.len(), 101 | 175) || !text.is_ascii() {
            return Err(AddressError::Encoding);
        }
        let mut parts = text.split(':');
        let domain = match parts.next() {
            Some("zvlab") => None,
            Some("zvlab2") => Some(unhex(parts.next().ok_or(AddressError::Encoding)?)?),
            _ => return Err(AddressError::Encoding),
        };
        let raw = unhex(parts.next().ok_or(AddressError::Encoding)?)?;
        parts.next().ok_or(AddressError::Encoding)?;
        if parts.next().is_some() {
            return Err(AddressError::Encoding);
        }
        let address = Option::<Address>::from(Address::from_raw_address_bytes(&raw))
            .ok_or(AddressError::Encoding)?;
        let result = Self::new(address, domain)?;
        if result.encode() != text {
            return Err(AddressError::Encoding);
        }
        Ok(result)
    }
    /// Expected domain must come from verified local history or a pinned genesis,
    /// never be selected by this recipient's text. None means legacy LAB1 only.
    pub fn for_domain(&self, expected: Option<[u8; 32]>) -> Result<Address, AddressError> {
        if self.domain != expected {
            return Err(AddressError::Network);
        }
        Ok(self.address)
    }
}
