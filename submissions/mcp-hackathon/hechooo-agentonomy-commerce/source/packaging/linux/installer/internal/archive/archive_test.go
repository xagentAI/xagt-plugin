package archive_test

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	"strings"
	"testing"
	"time"

	"github.com/HEchooo/Clink/packaging/linux/installer/internal/archive"
)

type member struct {
	name     string
	mode     int64
	data     []byte
	typeflag byte
}

func testKey() (ed25519.PrivateKey, ed25519.PublicKey) {
	seed := bytes.Repeat([]byte{0x42}, ed25519.SeedSize)
	private := ed25519.NewKeyFromSeed(seed)
	return private, private.Public().(ed25519.PublicKey)
}

func signedMembers(t *testing.T, payload []byte) []member {
	t.Helper()
	return signedMembersForPayload(t, payload, true)
}

func signedMembersWithoutLegalFiles(t *testing.T, payload []byte) []member {
	t.Helper()
	return signedMembersForPayload(t, payload, false)
}

func signedMembersForPayload(t *testing.T, payload []byte, includeLegalFiles bool) []member {
	t.Helper()
	private, _ := testKey()
	files := []any{
		map[string]any{
			"mode":   "0755",
			"path":   "payload/bin/clink-launcher",
			"sha256": archive.SHA256Hex(payload),
			"size":   len(payload),
		},
	}
	if includeLegalFiles {
		files = append(files,
			map[string]any{
				"mode":   "0644",
				"path":   "payload/LICENSE",
				"sha256": archive.SHA256Hex([]byte("operator license")),
				"size":   len("operator license"),
			},
			map[string]any{
				"mode":   "0644",
				"path":   "payload/NOTICE",
				"sha256": archive.SHA256Hex([]byte("operator notice")),
				"size":   len("operator notice"),
			},
		)
	}
	metadata := map[string]any{
		"created_at":        "2023-11-14T22:13:20Z",
		"entrypoint":        "payload/bin/clink-launcher",
		"files":             files,
		"platform":          "linux-x86_64",
		"schema_version":    1,
		"source_date_epoch": 1700000000,
		"version":           "1.2.3",
	}
	metadataBytes, err := archive.CanonicalJSON(metadata)
	if err != nil {
		t.Fatalf("canonical metadata: %v", err)
	}
	members := []member{
		{name: "release-metadata.json", mode: 0644, data: metadataBytes},
		{name: "release-signature.ed25519", mode: 0644, data: []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, metadataBytes)) + "\n")},
		{name: "payload/bin/clink-launcher", mode: 0755, data: payload},
	}
	if includeLegalFiles {
		members = append(members,
			member{name: "payload/LICENSE", mode: 0644, data: []byte("operator license")},
			member{name: "payload/NOTICE", mode: 0644, data: []byte("operator notice")},
		)
	}
	return members
}

func hostedResponseKeyID(t *testing.T, jwk map[string]string) string {
	t.Helper()
	canonical, err := archive.CanonicalJSON(map[string]string{
		"crv": jwk["crv"],
		"kty": jwk["kty"],
		"x":   jwk["x"],
		"y":   jwk["y"],
	})
	if err != nil {
		t.Fatalf("canonical response JWK: %v", err)
	}
	digest := sha256.Sum256(canonical)
	return base64.RawURLEncoding.EncodeToString(digest[:])
}

func hostedEnrollmentMetadata(t *testing.T) map[string]any {
	t.Helper()
	baseJWK := map[string]string{
		"kty": "EC",
		"crv": "P-256",
		"x":   "axfR8uEsQkf4vOblY6RA8ncDfYEt6zOg9KE5RdiYwpY",
		"y":   "T-NC4v4af5uO5-tKfA-eFivOM1drMV7Oy7ZAaDe_UfU",
	}
	polygonJWK := map[string]string{
		"kty": "EC",
		"crv": "P-256",
		"x":   "fPJ7GI0DT36KUjgDBLUaw8CJaeJ38hs1pgtI_EdmmXg",
		"y":   "B3dVENuO0EApPZrGn3Qw27p9reY86YIpngS3nSJ4c9E",
	}
	return map[string]any{
		"schema_version":      1,
		"enrollment_endpoint": "https://enroll.agentonomy.example/v1/enrollments",
		"targets": []any{
			map[string]any{
				"chain_id":            8453,
				"chain":               "eip155:8453",
				"token":               "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
				"origin":              "https://base.agentonomy.example",
				"response_public_jwk": baseJWK,
				"response_key_id":     hostedResponseKeyID(t, baseJWK),
				"executor_contract":   "0x" + strings.Repeat("11", 20),
			},
			map[string]any{
				"chain_id":            137,
				"chain":               "eip155:137",
				"token":               "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
				"origin":              "https://polygon.agentonomy.example",
				"response_public_jwk": polygonJWK,
				"response_key_id":     hostedResponseKeyID(t, polygonJWK),
				"executor_contract":   "0x" + strings.Repeat("22", 20),
			},
		},
	}
}

func signedHostedMembers(t *testing.T, payload []byte, hosted map[string]any) []member {
	t.Helper()
	private, _ := testKey()
	metadata := map[string]any{
		"created_at": "2023-11-14T22:13:20Z",
		"entrypoint": "payload/bin/clink-launcher",
		"files": []any{
			map[string]any{
				"mode": "0755", "path": "payload/bin/clink-launcher",
				"sha256": archive.SHA256Hex(payload), "size": len(payload),
			},
			map[string]any{
				"mode": "0644", "path": "payload/LICENSE",
				"sha256": archive.SHA256Hex([]byte("operator license")), "size": len("operator license"),
			},
			map[string]any{
				"mode": "0644", "path": "payload/NOTICE",
				"sha256": archive.SHA256Hex([]byte("operator notice")), "size": len("operator notice"),
			},
		},
		"hosted_enrollment": hosted,
		"platform":          "linux-x86_64",
		"schema_version":    1,
		"source_date_epoch": 1700000000,
		"version":           "1.2.3",
	}
	metadataBytes, err := archive.CanonicalJSON(metadata)
	if err != nil {
		t.Fatalf("canonical hosted metadata: %v", err)
	}
	return []member{
		{name: "release-metadata.json", mode: 0644, data: metadataBytes},
		{name: "release-signature.ed25519", mode: 0644, data: []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, metadataBytes)) + "\n")},
		{name: "payload/bin/clink-launcher", mode: 0755, data: payload},
		{name: "payload/LICENSE", mode: 0644, data: []byte("operator license")},
		{name: "payload/NOTICE", mode: 0644, data: []byte("operator notice")},
	}
}

func signedMembersForExtraFile(t *testing.T, path string, data []byte) []member {
	t.Helper()
	private, _ := testKey()
	launcher := []byte("launcher")
	license := []byte("operator license")
	notice := []byte("operator notice")
	files := []any{
		map[string]any{
			"mode":   "0755",
			"path":   "payload/bin/clink-launcher",
			"sha256": archive.SHA256Hex(launcher),
			"size":   len(launcher),
		},
		map[string]any{
			"mode":   "0644",
			"path":   "payload/LICENSE",
			"sha256": archive.SHA256Hex(license),
			"size":   len(license),
		},
		map[string]any{
			"mode":   "0644",
			"path":   "payload/NOTICE",
			"sha256": archive.SHA256Hex(notice),
			"size":   len(notice),
		},
		map[string]any{
			"mode":   "0644",
			"path":   path,
			"sha256": archive.SHA256Hex(data),
			"size":   len(data),
		},
	}
	metadata := map[string]any{
		"created_at":        "2023-11-14T22:13:20Z",
		"entrypoint":        "payload/bin/clink-launcher",
		"files":             files,
		"platform":          "linux-x86_64",
		"schema_version":    1,
		"source_date_epoch": 1700000000,
		"version":           "1.2.3",
	}
	metadataBytes, err := archive.CanonicalJSON(metadata)
	if err != nil {
		t.Fatalf("canonical metadata: %v", err)
	}
	return []member{
		{name: "release-metadata.json", mode: 0644, data: metadataBytes},
		{name: "release-signature.ed25519", mode: 0644, data: []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, metadataBytes)) + "\n")},
		{name: "payload/bin/clink-launcher", mode: 0755, data: launcher},
		{name: "payload/LICENSE", mode: 0644, data: license},
		{name: "payload/NOTICE", mode: 0644, data: notice},
		{name: path, mode: 0644, data: data},
	}
}

func publicCAPEM(t *testing.T, isCA bool) []byte {
	t.Helper()
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("generate certificate key: %v", err)
	}
	serial := big.NewInt(1)
	template := &x509.Certificate{
		SerialNumber:          serial,
		NotBefore:             time.Unix(1700000000, 0),
		NotAfter:              time.Unix(1800000000, 0),
		BasicConstraintsValid: true,
		IsCA:                  isCA,
		KeyUsage:              x509.KeyUsageCertSign,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, publicKey, privateKey)
	if err != nil {
		t.Fatalf("create certificate: %v", err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
}

const legacyV1CertificatePEM = `-----BEGIN CERTIFICATE-----
MIIEGjCCAwICEQCbfgZJoz5iudXukEhxKe9XMA0GCSqGSIb3DQEBBQUAMIHKMQsw
CQYDVQQGEwJVUzEXMBUGA1UEChMOVmVyaVNpZ24sIEluYy4xHzAdBgNVBAsTFlZl
cmlTaWduIFRydXN0IE5ldHdvcmsxOjA4BgNVBAsTMShjKSAxOTk5IFZlcmlTaWdu
LCBJbmMuIC0gRm9yIGF1dGhvcml6ZWQgdXNlIG9ubHkxRTBDBgNVBAMTPFZlcmlT
aWduIENsYXNzIDMgUHVibGljIFByaW1hcnkgQ2VydGlmaWNhdGlvbiBBdXRob3Jp
dHkgLSBHMzAeFw05OTEwMDEwMDAwMDBaFw0zNjA3MTYyMzU5NTlaMIHKMQsw
CQYDVQQGEwJVUzEXMBUGA1UEChMOVmVyaVNpZ24sIEluYy4xHzAdBgNVBAsTFlZl
cmlTaWduIFRydXN0IE5ldHdvcmsxOjA4BgNVBAsTMShjKSAxOTk5IFZlcmlTaWduLCBJ
bmMuIC0gRm9yIGF1dGhvcml6ZWQgdXNlIG9ubHkxRTBDBgNVBAMTPFZlcmlTaWdu
IENsYXNzIDMgUHVibGljIFByaW1hcnkgQ2VydGlmaWNhdGlvbiBBdXRob3JpdHkg
LSBHMzCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAMu6nFL8eB8aHm8b
N3O9+MlrlBIwT/A2R/XQkQr1F8ilYcEWQE37imGQ5XYgwREGfassbqb1EUGO+i2t
KmFZpGcmTNDovFJbcCAEWNF6yaRpvIMXZK0Fi7zQWM6NjPXr8EJJC52XJ2cybuGu
kxUccLwgTS8Y3pKI6GyFVxEa6X7jJhFUokWWVYPKMIno3Nij7SqAP395ZVc+FSBm
CC+Vk7+qRy+oRpfwEuL+wgorUeZ25rdGt+INpsyow0xZVYnm6FNcHOqd8GIWC6fJ
Xwzw3sJ2zq/3avL6QaaiMxTJ5Xpj055iN9WFZZ4O5lMkdBteHRJTW8cs54NJOxWu
imi5V5cCAwEAATANBgkqhkiG9w0BAQUFAAOCAQEAERSWwauSCPc/L8my/uRan2Te
2yFPhpk0djZX3dAVL8WtfxUfN2JzPtTnX84XA9s1+ivbrmAJXx5fj267Cz3qWhMe
DGBvtcC1IyIuBwvLqXTLR7sdwdela8wv0kL9Sd2nic9TutoAWii/gt/4uhMdUIaC
/Y4wjylGsB49Ndo4YhYYSq3mtlFs3q9i6wHQHiT+eo8SGhJouPtmmRQURVyu565p
F4ErWjfJXir0xuKhXFSbplQAz/DxwceYMBo7Nhbbo27q/a2ywtrvAkcTisDxszGt
TxzhT5yvDwyd93gN2PQ1VoDat20Xj50egWTh/sVFuq1ruQp6Tk9LhO5L8X3dEQ==
-----END CERTIFICATE-----
`

func legacyCAPEM(t *testing.T, v3NoConstraints, validSignature, selfIssued bool) []byte {
	t.Helper()
	if !v3NoConstraints {
		block, rest := pem.Decode([]byte(legacyV1CertificatePEM))
		if block == nil || len(rest) != 0 {
			t.Fatal("embedded legacy certificate did not decode cleanly")
		}
		certificate, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			t.Fatalf("parse embedded legacy certificate: %v", err)
		}
		der := append([]byte(nil), block.Bytes...)
		if !validSignature {
			der[len(der)-1] ^= 1
		}
		if !selfIssued {
			offset := bytes.Index(der, certificate.RawIssuer)
			if offset < 0 {
				t.Fatal("embedded legacy issuer not found")
			}
			replacement := bytes.Replace(certificate.RawIssuer, []byte("VeriSign"), []byte("XeriSign"), 1)
			if len(replacement) != len(certificate.RawIssuer) {
				t.Fatal("legacy issuer replacement changed length")
			}
			copy(der[offset:], replacement)
		}
		return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	}
	subjectPublic, subjectPrivate, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("generate subject key: %v", err)
	}
	_, otherPrivate, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("generate signer key: %v", err)
	}
	signer := subjectPrivate
	if !validSignature {
		signer = otherPrivate
	}
	name := pkix.Name{CommonName: "legacy-ca"}
	issuer := name
	if !selfIssued {
		issuer = pkix.Name{CommonName: "different-issuer"}
	}
	template := &x509.Certificate{
		SerialNumber: big.NewInt(2),
		Subject:      name,
		Issuer:       issuer,
		NotBefore:    time.Unix(1700000000, 0),
		NotAfter:     time.Unix(1800000000, 0),
	}
	template.DNSNames = []string{"legacy.example.test"}
	parent := &x509.Certificate{Subject: issuer}
	der, err := x509.CreateCertificate(rand.Reader, template, parent, subjectPublic, signer)
	if err != nil {
		t.Fatalf("create legacy certificate: %v", err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
}

func hasEntry(entries []archive.Entry, wanted string) bool {
	for _, entry := range entries {
		if entry.Path == wanted {
			return true
		}
	}
	return false
}

func tarGz(t *testing.T, members ...member) *bytes.Reader {
	t.Helper()
	var raw bytes.Buffer
	zipped := gzip.NewWriter(&raw)
	tarWriter := tar.NewWriter(zipped)
	for _, current := range members {
		header := &tar.Header{
			Name:     current.name,
			Mode:     current.mode,
			Size:     int64(len(current.data)),
			Typeflag: current.typeflag,
		}
		if current.typeflag == 0 {
			header.Typeflag = tar.TypeReg
		}
		if err := tarWriter.WriteHeader(header); err != nil {
			t.Fatalf("write tar header: %v", err)
		}
		if len(current.data) > 0 {
			if _, err := tarWriter.Write(current.data); err != nil {
				t.Fatalf("write tar member: %v", err)
			}
		}
	}
	if err := tarWriter.Close(); err != nil {
		t.Fatalf("close tar: %v", err)
	}
	if err := zipped.Close(); err != nil {
		t.Fatalf("close gzip: %v", err)
	}
	return bytes.NewReader(raw.Bytes())
}

func TestVerifySignedCanonicalBundle(t *testing.T) {
	_, public := testKey()
	bundle, err := archive.Verify(tarGz(t, signedMembers(t, []byte("launcher"))...), public)
	if err != nil {
		t.Fatalf("verify bundle: %v", err)
	}
	defer bundle.Close()
	if bundle.Metadata.Version != "1.2.3" {
		t.Fatalf("version = %q", bundle.Metadata.Version)
	}
	if len(bundle.Entries) != 3 || !hasEntry(bundle.Entries, "payload/bin/clink-launcher") {
		t.Fatalf("unexpected entries: %#v", bundle.Entries)
	}
}

func TestVerifyAndExtractPAXLongPayloadPath(t *testing.T) {
	private, public := testKey()
	longPath := "payload/runtime/lib/python3.12/site-packages/botocore/data/" +
		"license-manager-linux-subscriptions/2018-05-10/endpoint-rule-set-1.json.gz"
	launcher := []byte("launcher")
	license := []byte("operator license")
	notice := []byte("operator notice")
	longPayload := []byte("endpoint rules")
	files := []any{
		map[string]any{
			"mode":   "0755",
			"path":   "payload/bin/clink-launcher",
			"sha256": archive.SHA256Hex(launcher),
			"size":   len(launcher),
		},
		map[string]any{
			"mode":   "0644",
			"path":   "payload/LICENSE",
			"sha256": archive.SHA256Hex(license),
			"size":   len(license),
		},
		map[string]any{
			"mode":   "0644",
			"path":   "payload/NOTICE",
			"sha256": archive.SHA256Hex(notice),
			"size":   len(notice),
		},
		map[string]any{
			"mode":   "0644",
			"path":   longPath,
			"sha256": archive.SHA256Hex(longPayload),
			"size":   len(longPayload),
		},
	}
	metadata := map[string]any{
		"created_at":        "2023-11-14T22:13:20Z",
		"entrypoint":        "payload/bin/clink-launcher",
		"files":             files,
		"platform":          "linux-x86_64",
		"schema_version":    1,
		"source_date_epoch": 1700000000,
		"version":           "1.2.3",
	}
	metadataBytes, err := archive.CanonicalJSON(metadata)
	if err != nil {
		t.Fatalf("canonical metadata: %v", err)
	}
	members := []member{
		{name: "release-metadata.json", mode: 0644, data: metadataBytes},
		{name: "release-signature.ed25519", mode: 0644, data: []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, metadataBytes)) + "\n")},
		{name: "payload/bin/clink-launcher", mode: 0755, data: launcher},
		{name: "payload/LICENSE", mode: 0644, data: license},
		{name: "payload/NOTICE", mode: 0644, data: notice},
		{name: longPath, mode: 0644, data: longPayload},
	}
	bundle, err := archive.Verify(tarGz(t, members...), public)
	if err != nil {
		t.Fatalf("verify PAX bundle: %v", err)
	}
	defer bundle.Close()
	for _, entry := range bundle.Entries {
		if entry.Path != longPath {
			continue
		}
		file, openErr := entry.Open()
		if openErr != nil {
			t.Fatalf("open long PAX member: %v", openErr)
		}
		content, readErr := io.ReadAll(file)
		_ = file.Close()
		if readErr != nil {
			t.Fatalf("read long PAX member: %v", readErr)
		}
		if !bytes.Equal(content, longPayload) {
			t.Fatalf("long PAX member content = %q", content)
		}
		return
	}
	t.Fatalf("long PAX member %q not found", longPath)
}

func TestVerifyAcceptsPublicCACertificatePEM(t *testing.T) {
	_, public := testKey()
	certificate := append([]byte("\n# Issuer: Test CA\n"), publicCAPEM(t, true)...)
	bundle, err := archive.Verify(
		tarGz(t, signedMembersForExtraFile(t, "payload/runtime/cacert.pem", certificate)...),
		public,
	)
	if err != nil {
		t.Fatalf("verify public CA certificate: %v", err)
	}
	bundle.Close()
}

func TestVerifyAcceptsLegacyV1SelfSignedCAPEM(t *testing.T) {
	_, public := testKey()
	bundle, err := archive.Verify(
		tarGz(t, signedMembersForExtraFile(t, "payload/runtime/legacy-ca.pem", legacyCAPEM(t, false, true, true))...),
		public,
	)
	if err != nil {
		t.Fatalf("verify legacy v1 self-signed certificate: %v", err)
	}
	bundle.Close()
}

func TestVerifyRejectsUnsafeLegacyCAPEMVariants(t *testing.T) {
	tests := []struct {
		name string
		data []byte
	}{
		{name: "v3 without basic constraints", data: legacyCAPEM(t, true, true, true)},
		{name: "invalid self-signature", data: legacyCAPEM(t, false, false, true)},
		{name: "non-self-issued", data: legacyCAPEM(t, false, true, false)},
	}
	for _, current := range tests {
		t.Run(current.name, func(t *testing.T) {
			_, public := testKey()
			_, err := archive.Verify(
				tarGz(t, signedMembersForExtraFile(t, "payload/runtime/legacy-ca.pem", current.data)...),
				public,
			)
			if err == nil {
				t.Fatal("unsafe legacy certificate was accepted")
			}
		})
	}
}

func TestVerifyRejectsPrivateMalformedUnknownOrNonCAPEM(t *testing.T) {
	valid := publicCAPEM(t, true)
	block, blockRest := pem.Decode(valid)
	if block == nil || len(blockRest) != 0 {
		t.Fatal("generated certificate PEM did not decode cleanly")
	}
	withHeaders := pem.EncodeToMemory(&pem.Block{
		Type:    "CERTIFICATE",
		Headers: map[string]string{"Proc-Type": "4,ENCRYPTED"},
		Bytes:   block.Bytes,
	})
	tests := []struct {
		name string
		path string
		data []byte
	}{
		{name: "private block", path: "payload/runtime/key.pem", data: []byte("-----BEGIN " + "PRIVATE KEY-----\nsecret\n-----END " + "PRIVATE KEY-----\n")},
		{name: "malformed certificate", path: "payload/runtime/cert.pem", data: []byte("-----BEGIN CERTIFICATE-----\nnot-a-certificate\n-----END CERTIFICATE-----\n")},
		{name: "unknown block", path: "payload/runtime/cert.pem", data: append(valid, []byte("\n-----BEGIN PUBLIC KEY-----\nunknown\n-----END PUBLIC KEY-----\n")...)},
		{name: "non CA certificate", path: "payload/runtime/cert.pem", data: publicCAPEM(t, false)},
		{name: "certificate headers", path: "payload/runtime/cert.pem", data: withHeaders},
		{name: "private key suffix", path: "payload/runtime/key.key", data: []byte("private")},
		{name: "pkcs12 suffix", path: "payload/runtime/key.p12", data: []byte("private")},
		{name: "pkcs12 legacy suffix", path: "payload/runtime/key.pfx", data: []byte("private")},
	}
	for _, current := range tests {
		t.Run(current.name, func(t *testing.T) {
			_, public := testKey()
			_, err := archive.Verify(
				tarGz(t, signedMembersForExtraFile(t, current.path, current.data)...),
				public,
			)
			if err == nil {
				t.Fatal("unsafe PEM was accepted")
			}
		})
	}
}

func TestVerifyRejectsOversizedPublicCAPEM(t *testing.T) {
	_, public := testKey()
	data := bytes.Repeat([]byte("x"), 1024*1024+1)
	_, err := archive.Verify(
		tarGz(t, signedMembersForExtraFile(t, "payload/runtime/cert.pem", data)...),
		public,
	)
	if err == nil {
		t.Fatal("oversized PEM was accepted")
	}
}

func TestVerifyAcceptsControlMetadataBelowEightMiB(t *testing.T) {
	private, public := testKey()
	launcher := []byte("launcher")
	license := []byte("operator license")
	notice := []byte("operator notice")
	files := []any{
		map[string]any{"mode": "0755", "path": "payload/bin/clink-launcher", "sha256": archive.SHA256Hex(launcher), "size": len(launcher)},
		map[string]any{"mode": "0644", "path": "payload/LICENSE", "sha256": archive.SHA256Hex(license), "size": len(license)},
		map[string]any{"mode": "0644", "path": "payload/NOTICE", "sha256": archive.SHA256Hex(notice), "size": len(notice)},
	}
	members := []member{
		{name: "payload/bin/clink-launcher", mode: 0755, data: launcher},
		{name: "payload/LICENSE", mode: 0644, data: license},
		{name: "payload/NOTICE", mode: 0644, data: notice},
	}
	for index := 0; index < 12_000; index++ {
		path := fmt.Sprintf("payload/metadata-size/file-%05d.txt", index)
		data := []byte("x")
		files = append(files, map[string]any{
			"mode":   "0644",
			"path":   path,
			"sha256": archive.SHA256Hex(data),
			"size":   len(data),
		})
		members = append(members, member{name: path, mode: 0644, data: data})
	}
	metadata := map[string]any{
		"created_at":        "2023-11-14T22:13:20Z",
		"entrypoint":        "payload/bin/clink-launcher",
		"files":             files,
		"platform":          "linux-x86_64",
		"schema_version":    1,
		"source_date_epoch": 1700000000,
		"version":           "1.2.3",
	}
	metadataBytes, err := archive.CanonicalJSON(metadata)
	if err != nil {
		t.Fatalf("canonical large metadata: %v", err)
	}
	if len(metadataBytes) <= 1024*1024 || int64(len(metadataBytes)) > archive.MaxControlMemberSize {
		t.Fatalf("metadata size = %d, want (1MiB, 8MiB]", len(metadataBytes))
	}
	members = append([]member{
		{name: "release-metadata.json", mode: 0644, data: metadataBytes},
		{name: "release-signature.ed25519", mode: 0644, data: []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, metadataBytes)) + "\n")},
	}, members...)
	bundle, err := archive.Verify(tarGz(t, members...), public)
	if err != nil {
		t.Fatalf("verify large metadata: %v", err)
	}
	bundle.Close()
}

func TestVerifyRejectsControlMetadataOverEightMiB(t *testing.T) {
	_, public := testKey()
	var raw bytes.Buffer
	zipped := gzip.NewWriter(&raw)
	tarWriter := tar.NewWriter(zipped)
	if err := tarWriter.WriteHeader(&tar.Header{
		Name:     "release-metadata.json",
		Mode:     0644,
		Size:     archive.MaxControlMemberSize + 1,
		Typeflag: tar.TypeReg,
	}); err != nil {
		t.Fatalf("write oversized control header: %v", err)
	}
	_ = tarWriter.Close()
	_ = zipped.Close()
	if _, err := archive.Verify(bytes.NewReader(raw.Bytes()), public); err == nil {
		t.Fatal("oversized control member was accepted")
	}
}

func TestVerifyAcceptsMaxPayloadWithChannelControlMembers(t *testing.T) {
	private, public := testKey()
	launcher := []byte("launcher")
	license := []byte("operator license")
	notice := []byte("operator notice")
	files := []any{
		map[string]any{"mode": "0755", "path": "payload/bin/clink-launcher", "sha256": archive.SHA256Hex(launcher), "size": len(launcher)},
		map[string]any{"mode": "0644", "path": "payload/LICENSE", "sha256": archive.SHA256Hex(license), "size": len(license)},
		map[string]any{"mode": "0644", "path": "payload/NOTICE", "sha256": archive.SHA256Hex(notice), "size": len(notice)},
	}
	members := []member{
		{name: "payload/bin/clink-launcher", mode: 0755, data: launcher},
		{name: "payload/LICENSE", mode: 0644, data: license},
		{name: "payload/NOTICE", mode: 0644, data: notice},
	}
	for index := 0; index < archive.MaxFiles-3; index++ {
		path := fmt.Sprintf("payload/metadata-size/file-%05d.txt", index)
		data := []byte("x")
		files = append(files, map[string]any{
			"mode":   "0644",
			"path":   path,
			"sha256": archive.SHA256Hex(data),
			"size":   len(data),
		})
		members = append(members, member{name: path, mode: 0644, data: data})
	}
	metadata := map[string]any{
		"created_at":        "2023-11-14T22:13:20Z",
		"entrypoint":        "payload/bin/clink-launcher",
		"files":             files,
		"platform":          "linux-x86_64",
		"schema_version":    1,
		"source_date_epoch": 1700000000,
		"version":           "1.2.3",
	}
	metadataBytes, err := archive.CanonicalJSON(metadata)
	if err != nil {
		t.Fatalf("canonical boundary metadata: %v", err)
	}
	channel := map[string]any{
		"bundle_sha256":             archive.SHA256Hex([]byte("bundle")),
		"bundle_url":                "https://releases.example/clink.tar.gz",
		"channel":                   "stable",
		"minimum_installer_version": "0.1.0",
		"platform":                  "linux-x86_64",
		"published_at":              "2023-11-14T22:13:20Z",
		"schema_version":            1,
		"version":                   "1.2.3",
	}
	channelBytes, err := archive.CanonicalJSON(channel)
	if err != nil {
		t.Fatalf("canonical boundary channel: %v", err)
	}
	members = append([]member{
		{name: "release-metadata.json", mode: 0644, data: metadataBytes},
		{name: "release-signature.ed25519", mode: 0644, data: []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, metadataBytes)) + "\n")},
		{name: "channel-metadata.json", mode: 0644, data: channelBytes},
		{name: "channel-signature.ed25519", mode: 0644, data: []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, channelBytes)) + "\n")},
	}, members...)
	bundle, err := archive.Verify(tarGz(t, members...), public)
	if err != nil {
		t.Fatalf("verify max payload with channel controls: %v", err)
	}
	bundle.Close()
}

func TestVerifyRequiresOperatorSuppliedLegalFiles(t *testing.T) {
	_, public := testKey()
	if _, err := archive.Verify(tarGz(t, signedMembersWithoutLegalFiles(t, []byte("launcher"))...), public); err == nil {
		t.Fatal("release without operator-supplied LICENSE and NOTICE was accepted")
	}
}

func TestVerifyRejectsUnsafeArchiveMembers(t *testing.T) {
	_, public := testKey()
	valid := signedMembers(t, []byte("launcher"))
	tests := []struct {
		name   string
		member member
	}{
		{name: "traversal", member: member{name: "../escape", mode: 0644, data: []byte("x")}},
		{name: "absolute", member: member{name: "/absolute", mode: 0644, data: []byte("x")}},
		{name: "symlink", member: member{name: "payload/link", mode: 0777, typeflag: tar.TypeSymlink}},
		{name: "device", member: member{name: "payload/device", mode: 0600, typeflag: tar.TypeChar}},
	}
	for _, current := range tests {
		t.Run(current.name, func(t *testing.T) {
			_, err := archive.Verify(tarGz(t, append(valid, current.member)...), public)
			if err == nil {
				t.Fatal("unsafe archive member was accepted")
			}
		})
	}
}

func TestVerifyRejectsOversizedMemberBeforeReadingBody(t *testing.T) {
	_, public := testKey()
	var raw bytes.Buffer
	zipped := gzip.NewWriter(&raw)
	tarWriter := tar.NewWriter(zipped)
	if err := tarWriter.WriteHeader(&tar.Header{
		Name:     "payload/oversized",
		Mode:     0644,
		Size:     archive.MaxFileSize + 1,
		Typeflag: tar.TypeReg,
	}); err != nil {
		t.Fatalf("write oversized header: %v", err)
	}
	_ = tarWriter.Close()
	_ = zipped.Close()
	if _, err := archive.Verify(bytes.NewReader(raw.Bytes()), public); err == nil {
		t.Fatal("oversized archive member was accepted")
	}
}

func TestVerifyRejectsUnsignedPayloadMember(t *testing.T) {
	_, public := testKey()
	valid := signedMembers(t, []byte("launcher"))
	valid = append(valid, member{name: "payload/unsigned", mode: 0644, data: []byte("x")})
	if _, err := archive.Verify(tarGz(t, valid...), public); err == nil {
		t.Fatal("unsigned payload member was accepted")
	}
}

func TestVerifyRejectsDuplicateMetadataObjectKeys(t *testing.T) {
	private, public := testKey()
	raw := []byte(`{"schema_version":1,"schema_version":2}`)
	if err := archive.VerifySignedJSON(raw, []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, raw))), public); err == nil {
		t.Fatal("duplicate metadata keys were accepted")
	}
}

func TestVerifyAcceptsSignedExactHostedEnrollmentTargets(t *testing.T) {
	_, public := testKey()
	bundle, err := archive.Verify(
		tarGz(t, signedHostedMembers(t, []byte("launcher"), hostedEnrollmentMetadata(t))...),
		public,
	)
	if err != nil {
		t.Fatalf("verify hosted release: %v", err)
	}
	defer bundle.Close()
	if bundle.Metadata.HostedEnrollment == nil {
		t.Fatal("hosted enrollment metadata was dropped")
	}
	if len(bundle.Metadata.HostedEnrollment.Targets) != 2 {
		t.Fatalf("hosted target count = %d, want 2", len(bundle.Metadata.HostedEnrollment.Targets))
	}
	if !bytes.Contains(bundle.MetadataBytes, []byte(`"hosted_enrollment"`)) {
		t.Fatal("hosted enrollment metadata was not covered by signed bytes")
	}
}

func TestVerifyAcceptsPerChainExecutorContracts(t *testing.T) {
	_, public := testKey()
	hosted := hostedEnrollmentMetadata(t)
	targets := hosted["targets"].([]any)
	targets[0].(map[string]any)["executor_contract"] = "0x" + strings.Repeat("11", 20)
	targets[1].(map[string]any)["executor_contract"] = "0x" + strings.Repeat("22", 20)
	if _, err := archive.Verify(
		tarGz(t, signedHostedMembers(t, []byte("launcher"), hosted)...),
		public,
	); err != nil {
		t.Fatalf("verify hosted release with executor contracts: %v", err)
	}
}

func TestVerifyRejectsTamperedHostedEnrollmentFields(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(map[string]any)
	}{
		{
			name: "response key",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				base := targets[0].(map[string]any)
				polygon := targets[1].(map[string]any)
				base["response_public_jwk"] = polygon["response_public_jwk"]
			},
		},
		{
			name: "thumbprint",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["response_key_id"] = strings.Repeat("A", 43)
			},
		},
		{
			name: "endpoint",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "http://base.agentonomy.example"
			},
		},
		{
			name: "chain",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["chain"] = "eip155:84532"
			},
		},
		{
			name: "token",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["token"] = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
			},
		},
		{
			name: "executor",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["executor_contract"] = "0x" + strings.Repeat("0", 40)
			},
		},
		{
			name: "curve",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				jwk := targets[0].(map[string]any)["response_public_jwk"].(map[string]string)
				jwk["crv"] = "secp256k1"
			},
		},
		{
			name: "point",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				jwk := targets[0].(map[string]any)["response_public_jwk"].(map[string]string)
				jwk["x"] = strings.Repeat("A", 43)
			},
		},
		{
			name: "unknown field",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["invite_code"] = "not-a-secret"
			},
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, public := testKey()
			hosted := hostedEnrollmentMetadata(t)
			testCase.mutate(hosted)
			if _, err := archive.Verify(
				tarGz(t, signedHostedMembers(t, []byte("launcher"), hosted)...),
				public,
			); err == nil {
				t.Fatal("tampered hosted enrollment metadata was accepted")
			}
		})
	}
}

func TestVerifyRejectsNonCanonicalHostedEnrollmentURLs(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(map[string]any)
	}{
		{
			name: "enrollment uppercase scheme",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "HTTPS://enroll.agentonomy.example/v1/enrollments"
			},
		},
		{
			name: "enrollment uppercase host",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://ENROLL.agentonomy.example/v1/enrollments"
			},
		},
		{
			name: "enrollment default port",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example:443/v1/enrollments"
			},
		},
		{
			name: "enrollment leading zero default port",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example:0443/v1/enrollments"
			},
		},
		{
			name: "enrollment leading zero custom port",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example:080/v1/enrollments"
			},
		},
		{
			name: "enrollment leading zero low port",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example:01/v1/enrollments"
			},
		},
		{
			name: "enrollment zero port",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example:0/v1/enrollments"
			},
		},
		{
			name: "enrollment encoded host",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll%2Eagentonomy.example/v1/enrollments"
			},
		},
		{
			name: "enrollment missing path",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example"
			},
		},
		{
			name: "enrollment root path",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example/"
			},
		},
		{
			name: "enrollment alternate path",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example/v1/register"
			},
		},
		{
			name: "enrollment double slash",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example//v1/enrollments"
			},
		},
		{
			name: "enrollment empty segment",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example/v1//enrollments"
			},
		},
		{
			name: "enrollment dot segment",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example/v1/./enrollments"
			},
		},
		{
			name: "enrollment parent segment",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example/v1/../enrollments"
			},
		},
		{
			name: "enrollment encoded parent segment",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example/v1/%2e%2e/enrollments"
			},
		},
		{
			name: "enrollment encoded slash",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example/v1/%2F/enrollments"
			},
		},
		{
			name: "enrollment encoded backslash",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example/v1/%5C/enrollments"
			},
		},
		{
			name: "enrollment literal backslash",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example/v1\\enrollments"
			},
		},
		{
			name: "enrollment port out of range",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example:99999/v1/enrollments"
			},
		},
		{
			name: "enrollment host backslash",
			mutate: func(metadata map[string]any) {
				metadata["enrollment_endpoint"] = "https://enroll.agentonomy.example\\"
			},
		},
		{
			name: "origin path",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example/path"
			},
		},
		{
			name: "origin uppercase host",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://BASE.agentonomy.example"
			},
		},
		{
			name: "origin trailing slash",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example/"
			},
		},
		{
			name: "origin default port",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example:443"
			},
		},
		{
			name: "origin leading zero default port",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example:0443"
			},
		},
		{
			name: "origin leading zero custom port",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example:080"
			},
		},
		{
			name: "origin leading zero low port",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example:01"
			},
		},
		{
			name: "origin zero port",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example:0"
			},
		},
		{
			name: "origin encoded host",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base%2Eagentonomy.example"
			},
		},
		{
			name: "origin double slash",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example//"
			},
		},
		{
			name: "origin encoded slash",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example/%2f"
			},
		},
		{
			name: "origin literal backslash",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example\\"
			},
		},
		{
			name: "origin port out of range",
			mutate: func(metadata map[string]any) {
				targets := metadata["targets"].([]any)
				targets[0].(map[string]any)["origin"] = "https://base.agentonomy.example:99999"
			},
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, public := testKey()
			hosted := hostedEnrollmentMetadata(t)
			testCase.mutate(hosted)
			if _, err := archive.Verify(
				tarGz(t, signedHostedMembers(t, []byte("launcher"), hosted)...),
				public,
			); err == nil {
				t.Fatal("non-canonical hosted URL was accepted")
			}
		})
	}
}

func TestVerifyChannelMetadataUsesTheSharedSignedCanonicalProfile(t *testing.T) {
	private, public := testKey()
	metadata := map[string]any{
		"bundle_sha256":             archive.SHA256Hex([]byte("bundle")),
		"bundle_url":                "https://releases.example/clink.tar.gz",
		"channel":                   "stable",
		"minimum_installer_version": "0.1.0",
		"platform":                  "linux-x86_64",
		"published_at":              "2023-11-14T22:13:20Z",
		"schema_version":            1,
		"version":                   "1.2.3",
	}
	canonical, err := archive.CanonicalJSON(metadata)
	if err != nil {
		t.Fatalf("canonical channel metadata: %v", err)
	}
	channel, err := archive.VerifyChannelMetadata(
		canonical,
		[]byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, canonical))),
		public,
	)
	if err != nil || channel.Version != "1.2.3" {
		t.Fatalf("channel verification = %#v, %v", channel, err)
	}
}
