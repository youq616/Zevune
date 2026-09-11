#![cfg(feature = "local-funding-lab")]

//! Public, no-funds genesis manifest boundary tests. No wallet secrets or
//! spendable fixtures are written to disk or included in test output.
use zevune_orchard_lab::pool::testnet::{TestGenesis, MAX_GENESIS_BYTES, TEST_SUPPLY};
use zevune_orchard_lab::wallet::Wallet;

#[test]
fn generation_requires_exact_supply_and_checked_arithmetic() {
    let first = Wallet::create().unwrap().receive_address(0).unwrap();
    let second = Wallet::create().unwrap().receive_address(0).unwrap();
    assert!(TEST_SUPPLY > 1 && TEST_SUPPLY < u64::MAX);
    assert!(TestGenesis::generate(&[]).is_err());
    assert!(TestGenesis::generate(&[(first, TEST_SUPPLY - 1)]).is_err());
    assert!(TestGenesis::generate(&[(first, TEST_SUPPLY + 1)]).is_err());
    assert!(TestGenesis::generate(&[(first, u64::MAX), (second, TEST_SUPPLY)]).is_err());
    let valid = TestGenesis::generate(&[(first, 1), (second, TEST_SUPPLY - 1)]).unwrap();
    let decoded = TestGenesis::decode(valid.bytes()).unwrap();
    assert_eq!(decoded.bytes(), valid.bytes());
    assert_eq!(decoded.digest(), valid.digest());
}

#[test]
fn every_truncated_manifest_is_rejected() {
    let address = Wallet::create().unwrap().receive_address(0).unwrap();
    let manifest = TestGenesis::generate(&[(address, TEST_SUPPLY)]).unwrap();
    for end in 0..manifest.bytes().len() {
        assert!(
            TestGenesis::decode(&manifest.bytes()[..end]).is_err(),
            "truncated public manifest accepted at length {end}"
        );
    }
}

#[test]
fn canonical_manifest_rejects_trailing_bytes_and_oversize_input() {
    let address = Wallet::create().unwrap().receive_address(0).unwrap();
    let manifest = TestGenesis::generate(&[(address, TEST_SUPPLY)]).unwrap();
    for suffix in [&[0u8][..], &[1u8][..], &[0u8; 32][..]] {
        let mut altered = manifest.bytes().to_vec();
        altered.extend_from_slice(suffix);
        assert!(TestGenesis::decode(&altered).is_err());
    }
    assert!(TestGenesis::decode(&vec![0; MAX_GENESIS_BYTES + 1]).is_err());
}

#[test]
fn unsupported_manifest_magic_is_rejected() {
    let address = Wallet::create().unwrap().receive_address(0).unwrap();
    let manifest = TestGenesis::generate(&[(address, TEST_SUPPLY)]).unwrap();
    assert!(manifest.bytes().len() >= 8);
    for index in 0..8 {
        let mut altered = manifest.bytes().to_vec();
        altered[index] ^= 0x80;
        assert!(TestGenesis::decode(&altered).is_err());
    }
}
