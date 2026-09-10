# Resident local wallet session

`zevune-wallet-session WALLET EXPECTED_GENESIS [--password-stdin]` keeps one local wallet unlocked until EOF or an exit request. It never listens on a network socket and is not a validator worker. Do not use real assets. The process and terminal must be trusted while unlocked.

The password is prompted without echo by default. Explicit automation mode reads ONLY the first bounded input line as the password; subsequent lines are commands. Passwords, seeds and viewing keys are never command-line arguments. Diagnostics use fixed failure codes. A malformed/oversized command closes the session.

Initialization validates the original payment genesis, constructs a fixed verifier and prepares public proving parameters. Only then does stdout emit a ready JSON object. This cost belongs to cold startup. Ready does not mean any payment is confirmed.

After receiving `ready`, send one JSON object per line, at most 8192 bytes, and consume the corresponding JSON response:

```json
{"op":"balance","id":1,"history":"PATH_TO_CHECKPOINT_VERIFIED_PUBLIC_EXPORT"}
{"op":"prepare","id":2,"history":"PATH_TO_CHECKPOINT_VERIFIED_PUBLIC_EXPORT","recipient":"ACTUAL_ZVTEST_ADDRESS","units":1000,"destination":"NEW_PUBLIC_TX_FILE"}
{"op":"exit","id":3}
```

The session replays and validates the public export using its expected genesis and cached verifier. It constructs a genuine new proof using cached public parameters, writes the public transaction file without overwriting anything, and reports `submitted:false,finality:false`. Submission and signed checkpoint verification remain the job of zevune-paynet. The session accepts no command that reveals a seed or viewing key, but its owning user can see their own balance.

Separate a cold-start measurement from warm request time. Reusing public parameters does not waive proof or signature verification. The resident client does not eliminate recipient synchronization, network latency, congestion or every metadata leak. This module is not an Internet-facing wallet daemon or a reviewed secure enclave.
