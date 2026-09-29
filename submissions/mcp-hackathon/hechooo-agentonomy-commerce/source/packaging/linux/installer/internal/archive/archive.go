// Package archive verifies signed Clink release archives before installation.
// It intentionally uses only the Go standard library so the installer can be
// built as a static binary without executing the release's Python runtime.
package archive

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/ed25519"
	"crypto/elliptic"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net/url"
	"os"
	"path"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	MetadataName               = "release-metadata.json"
	SignatureName              = "release-signature.ed25519"
	ChannelMetadataName        = "channel-metadata.json"
	ChannelSignatureName       = "channel-signature.ed25519"
	PayloadPrefix              = "payload/"
	MaxFiles                   = 20_000
	MaxFileSize          int64 = 512 * 1024 * 1024
	MaxTotalSize         int64 = 4 * 1024 * 1024 * 1024
	MaxControlMemberSize int64 = 8 * 1024 * 1024
)

const maxPublicCAPEMSize int64 = 1024 * 1024

// ReleaseFile is one regular payload file described by signed metadata.
type ReleaseFile struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
	Mode   string `json:"mode"`
}

// ReleaseMetadata is the signed release manifest emitted by the release
// builder. Fields are deliberately narrow so the installer cannot infer
// executable content from an unbound metadata extension.
type ReleaseMetadata struct {
	SchemaVersion    int                       `json:"schema_version"`
	Version          string                    `json:"version"`
	Platform         string                    `json:"platform"`
	Entrypoint       string                    `json:"entrypoint"`
	SourceDateEpoch  int64                     `json:"source_date_epoch"`
	CreatedAt        string                    `json:"created_at"`
	Files            []ReleaseFile             `json:"files"`
	HostedEnrollment *HostedEnrollmentMetadata `json:"hosted_enrollment,omitempty"`
}

// HostedEnrollmentMetadata is public trust data carried by a signed release.
// The release Ed25519 signature is the trust root; response keys are pins, not
// self-authenticating credentials. Credentials and enrollment invites never
// belong in this object.
type HostedEnrollmentMetadata struct {
	SchemaVersion      int                      `json:"schema_version"`
	EnrollmentEndpoint string                   `json:"enrollment_endpoint"`
	Targets            []HostedEnrollmentTarget `json:"targets"`
}

type HostedEnrollmentTarget struct {
	ChainID           int                     `json:"chain_id"`
	Chain             string                  `json:"chain"`
	Token             string                  `json:"token"`
	Origin            string                  `json:"origin"`
	ResponsePublicJWK HostedResponsePublicJWK `json:"response_public_jwk"`
	ResponseKeyID     string                  `json:"response_key_id"`
	ExecutorContract  string                  `json:"executor_contract"`
}

type HostedResponsePublicJWK struct {
	KTY string `json:"kty"`
	CRV string `json:"crv"`
	X   string `json:"x"`
	Y   string `json:"y"`
}

// ChannelMetadata is the signed channel pointer used to locate one release.
// The bundle itself remains authoritative for payload files and hashes.
type ChannelMetadata struct {
	SchemaVersion           int    `json:"schema_version"`
	Channel                 string `json:"channel"`
	Platform                string `json:"platform"`
	Version                 string `json:"version"`
	BundleURL               string `json:"bundle_url"`
	BundleSHA256            string `json:"bundle_sha256"`
	MinimumInstallerVersion string `json:"minimum_installer_version"`
	PublishedAt             string `json:"published_at"`
}

// Entry is a verified payload file. Open reads a private temporary spool file
// created by Verify; callers must close the Bundle after installation.
type Entry struct {
	Path   string
	SHA256 string
	Size   int64
	Mode   os.FileMode

	spoolPath string
}

// Open returns the verified payload bytes without interpreting archive paths.
func (entry Entry) Open() (*os.File, error) {
	if entry.spoolPath == "" {
		return nil, errors.New("archive entry is not backed by a verified spool")
	}
	return os.Open(entry.spoolPath)
}

// Bundle contains a verified manifest and payload spools ready for atomic
// installation. Close removes all temporary files owned by the bundle.
type Bundle struct {
	Metadata      ReleaseMetadata
	MetadataBytes []byte
	Signature     []byte
	Entries       []Entry

	tempDir string
}

// Close removes the temporary archive spool. It is safe to call repeatedly.
func (bundle *Bundle) Close() error {
	if bundle == nil || bundle.tempDir == "" {
		return nil
	}
	err := os.RemoveAll(bundle.tempDir)
	bundle.tempDir = ""
	return err
}

// SHA256Hex returns a lowercase SHA-256 digest for test/build helpers and
// callers constructing a signed manifest.
func SHA256Hex(data []byte) string {
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:])
}

// CanonicalJSON returns compact UTF-8 JSON with lexicographically sorted object
// keys, matching the Python release builder's canonical JSON profile.
func CanonicalJSON(value any) ([]byte, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	return canonicalizeJSONBytes(raw)
}

// VerifySignedJSON checks a base64 Ed25519 signature over exact canonical JSON
// bytes. It is shared by release and channel metadata verification.
func VerifySignedJSON(metadata, encodedSignature []byte, publicKey ed25519.PublicKey) error {
	canonical, err := canonicalizeJSONBytes(metadata)
	if err != nil {
		return fmt.Errorf("metadata is not valid JSON: %w", err)
	}
	if !bytes.Equal(canonical, metadata) {
		return errors.New("metadata is not canonical JSON")
	}
	encoded := bytes.TrimSpace(encodedSignature)
	if len(encoded) == 0 || len(encoded) > 128 {
		return errors.New("metadata signature is invalid")
	}
	signature, err := base64.StdEncoding.DecodeString(string(encoded))
	if err != nil || len(signature) != ed25519.SignatureSize {
		return errors.New("metadata signature is invalid")
	}
	if len(publicKey) != ed25519.PublicKeySize || !ed25519.Verify(publicKey, canonical, signature) {
		return errors.New("metadata signature is invalid")
	}
	return nil
}

// VerifyChannelMetadata verifies and parses the signed channel pointer. It
// does not fetch the URL; callers must fetch the bundle separately and still
// verify its release signature and archive contents.
func VerifyChannelMetadata(metadata, encodedSignature []byte, publicKey ed25519.PublicKey) (ChannelMetadata, error) {
	if err := VerifySignedJSON(metadata, encodedSignature, publicKey); err != nil {
		return ChannelMetadata{}, err
	}
	var channel ChannelMetadata
	if err := strictJSONUnmarshal(metadata, &channel); err != nil {
		return ChannelMetadata{}, errors.New("channel metadata is invalid")
	}
	if channel.SchemaVersion != 1 || channel.Channel == "" || channel.Platform != "linux-x86_64" || !safeVersion(channel.Version) || channel.MinimumInstallerVersion == "" || channel.PublishedAt == "" {
		return ChannelMetadata{}, errors.New("channel metadata is invalid")
	}
	parsedURL, err := url.Parse(channel.BundleURL)
	if err != nil || parsedURL.Scheme != "https" || parsedURL.Host == "" || parsedURL.User != nil || parsedURL.Fragment != "" {
		return ChannelMetadata{}, errors.New("channel bundle URL is invalid")
	}
	if len(channel.BundleSHA256) != sha256.Size*2 || channel.BundleSHA256 != strings.ToLower(channel.BundleSHA256) {
		return ChannelMetadata{}, errors.New("channel bundle hash is invalid")
	}
	if _, err := hex.DecodeString(channel.BundleSHA256); err != nil {
		return ChannelMetadata{}, errors.New("channel bundle hash is invalid")
	}
	return channel, nil
}

// Verify validates the gzip/tar structure, signed metadata, and every payload
// digest before returning any installable entries. Archive members are spooled
// to private temporary files rather than extracted into the target directory.
func Verify(reader io.Reader, publicKey ed25519.PublicKey) (*Bundle, error) {
	if reader == nil {
		return nil, errors.New("release archive is missing")
	}
	tempDir, err := os.MkdirTemp("", "clink-release-verify-")
	if err != nil {
		return nil, fmt.Errorf("create verification spool: %w", err)
	}
	bundle := &Bundle{tempDir: tempDir}
	cleanup := func(cause error) (*Bundle, error) {
		_ = bundle.Close()
		return nil, cause
	}

	zipped, err := gzip.NewReader(reader)
	if err != nil {
		return cleanup(fmt.Errorf("invalid gzip archive: %w", err))
	}
	defer zipped.Close()
	tarReader := tar.NewReader(zipped)
	members := make(map[string]spooledMember)
	var total int64
	for count := 0; ; count++ {
		header, nextErr := tarReader.Next()
		if errors.Is(nextErr, io.EOF) {
			break
		}
		if nextErr != nil {
			return cleanup(fmt.Errorf("invalid tar archive: %w", nextErr))
		}
		if count >= MaxFiles+4 {
			return cleanup(errors.New("release archive exceeds file-count limit"))
		}
		if !safeArchiveName(header.Name) {
			return cleanup(fmt.Errorf("unsafe archive member: %s", safeErrorName(header.Name)))
		}
		if header.Typeflag != tar.TypeReg {
			return cleanup(fmt.Errorf("unsafe archive member type: %s", safeErrorName(header.Name)))
		}
		if header.Mode&^int64(0o777) != 0 {
			return cleanup(fmt.Errorf("unsafe archive member mode: %s", safeErrorName(header.Name)))
		}
		if header.Size < 0 || header.Size > MaxFileSize {
			return cleanup(fmt.Errorf("archive member exceeds size limit: %s", safeErrorName(header.Name)))
		}
		if isControlMemberName(header.Name) && header.Size > MaxControlMemberSize {
			return cleanup(fmt.Errorf("signed control member exceeds size limit: %s", safeErrorName(header.Name)))
		}
		if isPEMPath(header.Name) && header.Size > maxPublicCAPEMSize {
			return cleanup(fmt.Errorf("public CA certificate exceeds size limit: %s", safeErrorName(header.Name)))
		}
		if total > MaxTotalSize-header.Size {
			return cleanup(errors.New("release archive exceeds total-size limit"))
		}
		if _, exists := members[header.Name]; exists {
			return cleanup(fmt.Errorf("duplicate archive member: %s", safeErrorName(header.Name)))
		}

		spool, err := os.CreateTemp(tempDir, "member-")
		if err != nil {
			return cleanup(fmt.Errorf("create archive spool: %w", err))
		}
		spoolPath := spool.Name()
		written, copyErr := io.CopyN(spool, tarReader, header.Size)
		closeErr := spool.Close()
		if copyErr != nil || closeErr != nil || written != header.Size {
			_ = os.Remove(spoolPath)
			return cleanup(fmt.Errorf("truncated archive member: %s", safeErrorName(header.Name)))
		}
		if !safeArchiveMember(header.Name, header.Size, spoolPath) {
			_ = os.Remove(spoolPath)
			return cleanup(fmt.Errorf("unsafe archive member: %s", safeErrorName(header.Name)))
		}
		members[header.Name] = spooledMember{
			name:      header.Name,
			mode:      os.FileMode(header.Mode & 0o777),
			size:      header.Size,
			spoolPath: spoolPath,
		}
		total += header.Size
	}

	metadataMember, ok := members[MetadataName]
	if !ok {
		return cleanup(errors.New("missing signed bundle member: release-metadata.json"))
	}
	signatureMember, ok := members[SignatureName]
	if !ok {
		return cleanup(errors.New("missing signed bundle member: release-signature.ed25519"))
	}
	if metadataMember.mode != 0o644 || signatureMember.mode != 0o644 {
		return cleanup(errors.New("signed metadata members must be mode 0644"))
	}
	metadataBytes, err := os.ReadFile(metadataMember.spoolPath)
	if err != nil {
		return cleanup(errors.New("cannot read release metadata"))
	}
	signatureBytes, err := os.ReadFile(signatureMember.spoolPath)
	if err != nil {
		return cleanup(errors.New("cannot read release signature"))
	}
	if err := VerifySignedJSON(metadataBytes, signatureBytes, publicKey); err != nil {
		return cleanup(fmt.Errorf("release metadata signature is invalid: %w", err))
	}
	var metadata ReleaseMetadata
	if err := strictJSONUnmarshal(metadataBytes, &metadata); err != nil {
		return cleanup(fmt.Errorf("release metadata is invalid: %w", err))
	}
	if err := validateMetadata(metadata); err != nil {
		return cleanup(err)
	}
	if len(metadata.Files) > MaxFiles {
		return cleanup(errors.New("release metadata exceeds file-count limit"))
	}

	entries := make([]Entry, 0, len(metadata.Files))
	expected := map[string]bool{
		MetadataName:  true,
		SignatureName: true,
	}
	hasChannelMetadata, hasChannelSignature := false, false
	if channelMember, ok := members[ChannelMetadataName]; ok {
		hasChannelMetadata = true
		if channelMember.mode != 0o644 {
			return cleanup(errors.New("channel metadata members must be mode 0644"))
		}
		expected[ChannelMetadataName] = true
	}
	if channelMember, ok := members[ChannelSignatureName]; ok {
		hasChannelSignature = true
		if channelMember.mode != 0o644 {
			return cleanup(errors.New("channel metadata members must be mode 0644"))
		}
		expected[ChannelSignatureName] = true
	}
	if hasChannelMetadata != hasChannelSignature {
		return cleanup(errors.New("channel metadata signature is missing"))
	}
	for _, file := range metadata.Files {
		if !safePayloadName(file.Path) || file.Path == MetadataName || file.Path == SignatureName {
			return cleanup(errors.New("release metadata contains an unsafe payload path"))
		}
		if expected[file.Path] {
			return cleanup(fmt.Errorf("duplicate release metadata path: %s", safeErrorName(file.Path)))
		}
		member, found := members[file.Path]
		if !found {
			return cleanup(fmt.Errorf("missing payload member: %s", safeErrorName(file.Path)))
		}
		if file.Size < 0 || file.Size > MaxFileSize || file.Size != member.size {
			return cleanup(fmt.Errorf("payload size mismatch: %s", safeErrorName(file.Path)))
		}
		mode, err := parseMode(file.Mode)
		if err != nil || mode != member.mode {
			return cleanup(fmt.Errorf("payload mode mismatch: %s", safeErrorName(file.Path)))
		}
		if file.SHA256 != strings.ToLower(file.SHA256) || len(file.SHA256) != sha256.Size*2 {
			return cleanup(fmt.Errorf("payload hash is invalid: %s", safeErrorName(file.Path)))
		}
		if _, err := hex.DecodeString(file.SHA256); err != nil {
			return cleanup(fmt.Errorf("payload hash is invalid: %s", safeErrorName(file.Path)))
		}
		digest, err := fileDigest(member.spoolPath)
		if err != nil || digest != file.SHA256 {
			return cleanup(fmt.Errorf("payload hash mismatch: %s", safeErrorName(file.Path)))
		}
		expected[file.Path] = true
		entries = append(entries, Entry{
			Path:      file.Path,
			SHA256:    file.SHA256,
			Size:      file.Size,
			Mode:      mode,
			spoolPath: member.spoolPath,
		})
	}
	for name := range members {
		if !expected[name] {
			return cleanup(fmt.Errorf("archive contains unsigned member: %s", safeErrorName(name)))
		}
	}
	if !expected[metadata.Entrypoint] {
		return cleanup(errors.New("release entrypoint is not in payload manifest"))
	}
	entrypointMode := os.FileMode(0)
	for _, entry := range entries {
		if entry.Path == metadata.Entrypoint {
			entrypointMode = entry.Mode.Perm()
			break
		}
	}
	if entrypointMode != 0o755 {
		return cleanup(errors.New("release entrypoint must be executable"))
	}
	if hasChannelMetadata {
		channelSignature, found := members[ChannelSignatureName]
		if !found {
			return cleanup(errors.New("channel metadata signature is missing"))
		}
		channelBytes, readErr := os.ReadFile(members[ChannelMetadataName].spoolPath)
		channelSigBytes, sigErr := os.ReadFile(channelSignature.spoolPath)
		if readErr != nil || sigErr != nil {
			return cleanup(errors.New("channel metadata signature is invalid"))
		}
		if _, err := VerifyChannelMetadata(channelBytes, channelSigBytes, publicKey); err != nil {
			return cleanup(errors.New("channel metadata signature is invalid"))
		}
		delete(members, ChannelMetadataName)
		delete(members, ChannelSignatureName)
	}

	bundle.Metadata = metadata
	bundle.MetadataBytes = append([]byte(nil), metadataBytes...)
	bundle.Signature = append([]byte(nil), bytes.TrimSpace(signatureBytes)...)
	bundle.Entries = entries
	return bundle, nil
}

type spooledMember struct {
	name      string
	mode      os.FileMode
	size      int64
	spoolPath string
}

func canonicalizeJSONBytes(raw []byte) ([]byte, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	value, err := decodeJSONValue(decoder)
	if err != nil {
		return nil, err
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, errors.New("JSON contains trailing values")
		}
		return nil, err
	}
	var output bytes.Buffer
	if err := writeCanonicalJSON(&output, value); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

func decodeJSONValue(decoder *json.Decoder) (any, error) {
	token, err := decoder.Token()
	if err != nil {
		return nil, err
	}
	switch value := token.(type) {
	case json.Delim:
		switch value {
		case '{':
			object := make(map[string]any)
			for decoder.More() {
				keyToken, err := decoder.Token()
				if err != nil {
					return nil, err
				}
				key, ok := keyToken.(string)
				if !ok {
					return nil, errors.New("JSON object key is not a string")
				}
				if _, exists := object[key]; exists {
					return nil, fmt.Errorf("duplicate JSON object key: %s", key)
				}
				member, err := decodeJSONValue(decoder)
				if err != nil {
					return nil, err
				}
				object[key] = member
			}
			_, err := decoder.Token()
			return object, err
		case '[':
			array := make([]any, 0)
			for decoder.More() {
				member, err := decodeJSONValue(decoder)
				if err != nil {
					return nil, err
				}
				array = append(array, member)
			}
			_, err := decoder.Token()
			return array, err
		default:
			return nil, errors.New("unexpected JSON delimiter")
		}
	default:
		return value, nil
	}
}

func writeCanonicalJSON(output *bytes.Buffer, value any) error {
	switch current := value.(type) {
	case nil:
		output.WriteString("null")
	case bool:
		if current {
			output.WriteString("true")
		} else {
			output.WriteString("false")
		}
	case string:
		encoded, err := marshalJSONString(current)
		if err != nil {
			return err
		}
		output.Write(encoded)
	case json.Number:
		if _, err := strconv.ParseFloat(string(current), 64); err != nil {
			return fmt.Errorf("invalid JSON number: %w", err)
		}
		output.WriteString(string(current))
	case []any:
		output.WriteByte('[')
		for index, item := range current {
			if index > 0 {
				output.WriteByte(',')
			}
			if err := writeCanonicalJSON(output, item); err != nil {
				return err
			}
		}
		output.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(current))
		for key := range current {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		output.WriteByte('{')
		for index, key := range keys {
			if index > 0 {
				output.WriteByte(',')
			}
			encoded, err := marshalJSONString(key)
			if err != nil {
				return err
			}
			output.Write(encoded)
			output.WriteByte(':')
			if err := writeCanonicalJSON(output, current[key]); err != nil {
				return err
			}
		}
		output.WriteByte('}')
	default:
		return fmt.Errorf("unsupported JSON value %T", value)
	}
	return nil
}

func marshalJSONString(value string) ([]byte, error) {
	var output bytes.Buffer
	encoder := json.NewEncoder(&output)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(output.Bytes(), []byte{'\n'}), nil
}

func strictJSONUnmarshal(raw []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return errors.New("JSON contains trailing values")
	}
	return nil
}

func validateMetadata(metadata ReleaseMetadata) error {
	if metadata.SchemaVersion != 1 {
		return errors.New("unsupported release metadata schema")
	}
	if metadata.Platform != "linux-x86_64" {
		return errors.New("release platform is not linux-x86_64")
	}
	if !safeVersion(metadata.Version) {
		return errors.New("release version is invalid")
	}
	if !safePayloadName(metadata.Entrypoint) {
		return errors.New("release entrypoint is invalid")
	}
	if metadata.SourceDateEpoch < 0 || metadata.CreatedAt == "" {
		return errors.New("release metadata time is invalid")
	}
	hasLicense, hasNotice := false, false
	for _, file := range metadata.Files {
		switch file.Path {
		case "payload/LICENSE":
			hasLicense = true
		case "payload/NOTICE":
			hasNotice = true
		}
	}
	if !hasLicense || !hasNotice {
		return errors.New("release metadata requires operator-supplied LICENSE and NOTICE")
	}
	if metadata.HostedEnrollment != nil {
		if err := validateHostedEnrollment(*metadata.HostedEnrollment); err != nil {
			return err
		}
	}
	return nil
}

var hostedProductionTargets = map[int]struct {
	chain string
	token string
}{
	8453: {
		chain: "eip155:8453",
		token: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
	},
	137: {
		chain: "eip155:137",
		token: "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
	},
}

func validateHostedEnrollment(metadata HostedEnrollmentMetadata) error {
	if metadata.SchemaVersion != 1 {
		return errors.New("hosted enrollment schema is unsupported")
	}
	if err := validateHostedURL(metadata.EnrollmentEndpoint, false); err != nil {
		return fmt.Errorf("hosted enrollment endpoint is invalid: %w", err)
	}
	if len(metadata.Targets) != len(hostedProductionTargets) {
		return errors.New("hosted enrollment must contain exactly Base and Polygon targets")
	}
	seen := make(map[int]struct{}, len(metadata.Targets))
	for _, target := range metadata.Targets {
		if _, ok := hostedProductionTargets[target.ChainID]; !ok {
			return errors.New("hosted enrollment target chain is not production")
		}
		if _, ok := seen[target.ChainID]; ok {
			return errors.New("hosted enrollment contains duplicate chain")
		}
		seen[target.ChainID] = struct{}{}
		expected := hostedProductionTargets[target.ChainID]
		if target.Chain != expected.chain {
			return errors.New("hosted enrollment target chain is not canonical")
		}
		if target.Token != expected.token {
			return errors.New("hosted enrollment target token is not canonical")
		}
		if err := validateHostedEVMAddress(target.ExecutorContract); err != nil {
			return fmt.Errorf("hosted target executor contract is invalid: %w", err)
		}
		if err := validateHostedURL(target.Origin, true); err != nil {
			return fmt.Errorf("hosted target origin is invalid: %w", err)
		}
		keyID, err := validateHostedResponseJWK(target.ResponsePublicJWK)
		if err != nil {
			return err
		}
		if target.ResponseKeyID != keyID {
			return errors.New("hosted response key thumbprint does not match")
		}
	}
	if len(seen) != len(hostedProductionTargets) {
		return errors.New("hosted enrollment is missing a production chain")
	}
	return nil
}

func validateHostedEVMAddress(value string) error {
	if len(value) != 42 || !strings.HasPrefix(value, "0x") {
		return errors.New("executor contract must be a canonical EVM address")
	}
	for _, character := range value[2:] {
		if !(character >= '0' && character <= '9' || character >= 'a' && character <= 'f') {
			return errors.New("executor contract must be a canonical EVM address")
		}
	}
	if value == "0x"+strings.Repeat("0", 40) {
		return errors.New("executor contract must be non-zero")
	}
	return nil
}

func validateHostedURL(value string, origin bool) error {
	if !strings.HasPrefix(value, "https://") {
		return errors.New("endpoint must use lowercase HTTPS")
	}
	if strings.TrimSpace(value) != value || strings.Contains(value, "\\") {
		return errors.New("endpoint must use canonical HTTPS without credentials, query or fragment")
	}
	for _, runeValue := range value {
		if runeValue < 0x20 || runeValue == 0x7f || runeValue > 0x7f {
			return errors.New("endpoint must use canonical ASCII URL encoding")
		}
	}
	parsed, err := url.Parse(value)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.ForceQuery || parsed.Fragment != "" || parsed.Opaque != "" || strings.ContainsAny(value, "?#") {
		return errors.New("endpoint must use canonical HTTPS without credentials, query or fragment")
	}
	if _, err := url.ParseRequestURI(value); err != nil {
		return errors.New("endpoint is malformed")
	}
	if parsed.Hostname() == "" {
		return errors.New("endpoint host is missing")
	}
	if strings.Contains(parsed.Host, "%") || strings.HasSuffix(parsed.Host, ":") {
		return errors.New("endpoint host is not canonical")
	}
	canonicalPort := 0
	if port := parsed.Port(); port != "" {
		parsedPort, err := strconv.Atoi(port)
		if err != nil || parsedPort < 1 || parsedPort > 65535 {
			return errors.New("endpoint port is invalid")
		}
		canonicalPort = parsedPort
	}
	rawPath := parsed.EscapedPath()
	if parsed.RawPath != "" {
		rawPath = parsed.RawPath
	}
	if err := validateHostedPath(rawPath, origin); err != nil {
		return err
	}
	hostname := strings.ToLower(parsed.Hostname())
	if strings.Contains(hostname, ":") {
		hostname = "[" + hostname + "]"
	}
	canonicalHost := hostname
	if canonicalPort != 0 && canonicalPort != 443 {
		canonicalHost += ":" + strconv.Itoa(canonicalPort)
	}
	canonicalPath := "/v1/enrollments"
	if origin {
		canonicalPath = ""
	}
	if value != "https://"+canonicalHost+canonicalPath {
		return errors.New("endpoint is not canonical")
	}
	return nil
}

func validateHostedPath(rawPath string, origin bool) error {
	if origin {
		if rawPath != "" && rawPath != "/" {
			return errors.New("target endpoint must be an HTTPS origin")
		}
		return nil
	}
	if rawPath == "" || !strings.HasPrefix(rawPath, "/") || rawPath == "/" {
		return errors.New("enrollment endpoint path is invalid")
	}
	for _, segment := range strings.Split(rawPath[1:], "/") {
		if segment == "" || segment == "." || segment == ".." {
			return errors.New("enrollment endpoint path is not canonical")
		}
	}
	decoded := make([]byte, 0, len(rawPath))
	for index := 0; index < len(rawPath); {
		character := rawPath[index]
		if character == '%' {
			if index+2 >= len(rawPath) || !isHostedHex(rawPath[index+1]) || !isHostedHex(rawPath[index+2]) {
				return errors.New("enrollment endpoint path is invalid")
			}
			if rawPath[index+1] >= 'a' && rawPath[index+1] <= 'f' || rawPath[index+2] >= 'a' && rawPath[index+2] <= 'f' {
				return errors.New("enrollment endpoint path is not canonical")
			}
			decodedByte := hostedHexByte(rawPath[index+1], rawPath[index+2])
			if decodedByte == '/' || decodedByte == '\\' || decodedByte == '.' {
				return errors.New("enrollment endpoint path is not canonical")
			}
			if decodedByte < 0x80 && isHostedPathPChar(decodedByte) {
				return errors.New("enrollment endpoint path is not canonical")
			}
			decoded = append(decoded, decodedByte)
			index += 3
			continue
		}
		if character == '\\' || character < 0x20 || character == 0x7f || character >= 0x80 || (character != '/' && !isHostedPathPChar(character)) {
			return errors.New("enrollment endpoint path is not canonical")
		}
		decoded = append(decoded, character)
		index++
	}
	if !utf8.Valid(decoded) {
		return errors.New("enrollment endpoint path is invalid")
	}
	return nil
}

func isHostedPathPChar(value byte) bool {
	return value >= 'A' && value <= 'Z' || value >= 'a' && value <= 'z' || value >= '0' && value <= '9' || strings.ContainsRune("-._~!$&'()*+,;=:@", rune(value))
}

func isHostedHex(value byte) bool {
	return value >= '0' && value <= '9' || value >= 'A' && value <= 'F' || value >= 'a' && value <= 'f'
}

func hostedHexByte(high, low byte) byte {
	return hostedHexValue(high)<<4 | hostedHexValue(low)
}

func hostedHexValue(value byte) byte {
	switch {
	case value >= '0' && value <= '9':
		return value - '0'
	case value >= 'A' && value <= 'F':
		return value - 'A' + 10
	default:
		return value - 'a' + 10
	}
}

func validateHostedResponseJWK(jwk HostedResponsePublicJWK) (string, error) {
	if jwk.KTY != "EC" || jwk.CRV != "P-256" {
		return "", errors.New("hosted response public JWK must use P-256")
	}
	x, err := decodeHostedCoordinate(jwk.X)
	if err != nil {
		return "", errors.New("hosted response public JWK is invalid")
	}
	y, err := decodeHostedCoordinate(jwk.Y)
	if err != nil {
		return "", errors.New("hosted response public JWK is invalid")
	}
	if !elliptic.P256().IsOnCurve(new(big.Int).SetBytes(x), new(big.Int).SetBytes(y)) {
		return "", errors.New("hosted response public JWK point is invalid")
	}
	canonical, err := CanonicalJSON(map[string]string{
		"crv": jwk.CRV,
		"kty": jwk.KTY,
		"x":   jwk.X,
		"y":   jwk.Y,
	})
	if err != nil {
		return "", errors.New("hosted response public JWK is invalid")
	}
	digest := sha256.Sum256(canonical)
	return base64.RawURLEncoding.EncodeToString(digest[:]), nil
}

func decodeHostedCoordinate(value string) ([]byte, error) {
	if value == "" || strings.ContainsAny(value, "=+/\t\r\n ") {
		return nil, errors.New("coordinate is not canonical base64url")
	}
	decoded, err := base64.RawURLEncoding.DecodeString(value)
	if err != nil || len(decoded) != 32 || base64.RawURLEncoding.EncodeToString(decoded) != value {
		return nil, errors.New("coordinate is not canonical base64url")
	}
	return decoded, nil
}

func parseMode(value string) (os.FileMode, error) {
	if value != "0644" && value != "0755" {
		return 0, errors.New("release mode must be 0644 or 0755")
	}
	parsed, err := strconv.ParseUint(value, 8, 32)
	return os.FileMode(parsed), err
}

func fileDigest(name string) (string, error) {
	file, err := os.Open(name)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hasher := sha256.New()
	if _, err := io.Copy(hasher, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hasher.Sum(nil)), nil
}

func safeArchiveName(name string) bool {
	if name == "" || strings.ContainsRune(name, '\x00') || strings.Contains(name, "\\") || strings.HasPrefix(name, "/") {
		return false
	}
	for _, runeValue := range name {
		if unicode.IsControl(runeValue) {
			return false
		}
	}
	cleaned := path.Clean(name)
	if cleaned != name || cleaned == "." || strings.HasPrefix(cleaned, "../") || cleaned == ".." {
		return false
	}
	for _, part := range strings.Split(name, "/") {
		if part == "" || part == ".." {
			return false
		}
		lower := strings.ToLower(part)
		if lower == ".env" || lower == ".git" || lower == ".gitnexus" || lower == ".pytest_cache" || lower == "__pycache__" || lower == "node_modules" {
			return false
		}
		for _, suffix := range []string{".key", ".p12", ".pfx", ".pyc"} {
			if strings.HasSuffix(lower, suffix) {
				return false
			}
		}
	}
	return true
}

func isPEMPath(name string) bool {
	return strings.HasSuffix(strings.ToLower(name), ".pem")
}

func isControlMemberName(name string) bool {
	switch name {
	case MetadataName, SignatureName, ChannelMetadataName, ChannelSignatureName:
		return true
	default:
		return false
	}
}

func safeArchiveMember(name string, size int64, spoolPath string) bool {
	if !safeArchiveName(name) {
		return false
	}
	if !isPEMPath(name) {
		return true
	}
	if size < 1 || size > maxPublicCAPEMSize {
		return false
	}
	data, err := os.ReadFile(spoolPath)
	if err != nil {
		return false
	}
	return isPublicCACertificatePEM(data)
}

func isAllowedCAPEMComment(line []byte) bool {
	line = bytes.TrimSpace(line)
	if len(line) == 0 {
		return true
	}
	if line[0] != '#' {
		return false
	}
	line = bytes.TrimSpace(line[1:])
	for _, prefix := range []string{
		"Issuer:",
		"Subject:",
		"Label:",
		"Serial:",
		"MD5 Fingerprint:",
		"SHA1 Fingerprint:",
		"SHA256 Fingerprint:",
	} {
		if bytes.HasPrefix(line, []byte(prefix)) {
			return true
		}
	}
	return false
}

func isLegacySelfSignedV1(certificate *x509.Certificate) bool {
	return certificate.Version == 1 &&
		bytes.Equal(certificate.RawSubject, certificate.RawIssuer) &&
		certificate.CheckSignature(
			certificate.SignatureAlgorithm,
			certificate.RawTBSCertificate,
			certificate.Signature,
		) == nil
}

func isPublicCACertificatePEM(data []byte) bool {
	blocks := 0
	for len(data) > 0 {
		lineEnd := bytes.IndexByte(data, '\n')
		line := data
		if lineEnd >= 0 {
			line = data[:lineEnd]
		}
		trimmed := bytes.TrimSpace(line)
		if isAllowedCAPEMComment(trimmed) {
			if lineEnd < 0 {
				data = nil
			} else {
				data = data[lineEnd+1:]
			}
			continue
		}
		if !bytes.HasPrefix(trimmed, []byte("-----BEGIN ")) {
			return false
		}
		block, remainder := pem.Decode(data)
		if block == nil || block.Type != "CERTIFICATE" || len(block.Headers) != 0 {
			return false
		}
		certificate, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			return false
		}
		if certificate.BasicConstraintsValid {
			if !certificate.IsCA {
				return false
			}
		} else if !isLegacySelfSignedV1(certificate) {
			return false
		}
		blocks++
		data = remainder
	}
	return blocks > 0
}

func safePayloadName(name string) bool {
	return safeArchiveName(name) && strings.HasPrefix(name, PayloadPrefix)
}

func safeVersion(value string) bool {
	if value == "" || len(value) > 128 || strings.TrimSpace(value) != value {
		return false
	}
	for index, runeValue := range value {
		if !(runeValue >= 'a' && runeValue <= 'z') && !(runeValue >= 'A' && runeValue <= 'Z') && !(runeValue >= '0' && runeValue <= '9') && runeValue != '.' && runeValue != '_' && runeValue != '-' {
			return false
		}
		if index == 0 && (runeValue == '.' || runeValue == '-' || runeValue == '_') {
			return false
		}
	}
	return true
}

func safeErrorName(value string) string {
	if len(value) > 128 {
		return value[:128] + "..."
	}
	return value
}
