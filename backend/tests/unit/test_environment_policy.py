from sentinel.security.definition_policy import validate_environment_document


def test_environment_document_is_canonicalized_without_resolving_secrets() -> None:
    document = validate_environment_document(
        {
            "base_url": "HTTPS://Example.COM:443/api",
            "variables": {"REGION": "synthetic"},
            "secret_references": [{"$secret": "API_TOKEN"}],
            "target_policy": {
                "allowed_hostnames": ["EXAMPLE.COM"],
                "allowed_cidrs": ["203.0.113.0/24"],
                "denied_hostnames": [],
                "denied_cidrs": [],
                "allowed_ports": [8443, 443],
            },
        }
    )

    assert document.to_document() == {
        "schema_version": 1,
        "base_url": "https://example.com/api/",
        "variables": {"REGION": "synthetic"},
        "secret_references": [{"$secret": "API_TOKEN"}],
        "target_policy": {
            "schema_version": 1,
            "allowed_hostnames": ["example.com"],
            "allowed_cidrs": ["203.0.113.0/24"],
            "denied_hostnames": [],
            "denied_cidrs": [],
            "allowed_ports": [443, 8443],
        },
    }
