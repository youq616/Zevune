//! NO-FUNDS, local integration. Not a mainnet protocol or audited wallet.
#![forbid(unsafe_code)]
pub mod wire;
pub mod chain;
pub mod store;
pub mod wallet;
pub mod worker;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error { Encoding, Limit, Context, Authorization, State, Funds, Storage, Password, Address }
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { write!(f, "payment laboratory: {self:?}") }
}
impl std::error::Error for Error {}
pub type Result<T> = std::result::Result<T, Error>;
pub const CHAIN: &str = "zevune-payment-lab-1";
pub const SUPPLY: u64 = 1_000_000;
pub const FEE: u64 = 1_000;
