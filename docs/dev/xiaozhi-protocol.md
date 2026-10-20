# StackChan xiaozhi protocol notes

## Enrollment token exchange

The first hello reply after a valid enrollment code is presented includes
`maipai_token`, a one-time delivery of the long-lived per-device bearer token.
The firmware must persist this value to NVS at `websocket/token` and use it in
the `Authorization: Bearer` header on subsequent connections. Reconnecting with
the enrollment code is allowed only for the same Device-Id and Client-Id until
the real token authenticates successfully; that authentication spends the code.
