# Zevune Protocol v1

## Purpose

Protocol v1 introduces explicit domain separation between network identity, genesis configuration and transaction authorization.

## Transaction domain

Every future transaction must bind:

- chain identifier
- genesis digest
- validator set digest
- protocol version
- activation height

A valid signature in one domain must not be accepted in another domain.

## State transition

State changes must pass through a deterministic transition engine:

```
Previous State
      |
 Transaction + Proof
      |
 Validation
      |
 New State Root
```

The transition engine is responsible for:

- authorization verification
- nullifier checks
- balance conservation
- deterministic state root calculation

## Upgrade model

Protocol versions must activate at explicit heights and include migration rules.

This document is the initial protocol freeze draft. It is not yet a mainnet specification.
