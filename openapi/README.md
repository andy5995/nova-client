# Service API spec

`service-api.json` is the OpenAPI spec for the Nova Hub Service API: the endpoints a client
uses to sign in, upload and download packets, and fetch nodelists. It is everything you need
to write a client for another platform without reading the hub's source.

It is generated, not written by hand. In a nova-hub checkout:

```bash
.venv/bin/python export_openapi.py ../nova-client/openapi/service-api.json
```

`info.version` is the hub version it came from, and the commit that changes it here names the
hub tag. Paths are relative to the `/service` server entry, so `/api/v1/auth/token` is
`https://<hub>/service/api/v1/auth/token`.

`python/tests/test_openapi_spec.py` holds the mock hub that both client suites run against to
this file: the same routes, and response bodies of the shape it gives. When the hub's Service
API changes, regenerate it, commit it, and let that test say what the mock is missing.
