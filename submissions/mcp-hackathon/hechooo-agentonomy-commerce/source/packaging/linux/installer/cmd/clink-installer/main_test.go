package main

import (
	"crypto/ed25519"
	"encoding/base64"
	"strings"
	"testing"
)

func TestParsePublicKeyAcceptsHexAndBase64(t *testing.T) {
	key := ed25519.PublicKey(strings.Repeat("B", ed25519.PublicKeySize))
	hexKey := "0x" + strings.Repeat("42", ed25519.PublicKeySize)
	parsed, err := parsePublicKey(hexKey, "")
	if err != nil || string(parsed) != string(key) {
		t.Fatalf("hex key parse = %v, %x", err, parsed)
	}
	encoded := base64.StdEncoding.EncodeToString([]byte(key))
	parsed, err = parsePublicKey(encoded, "")
	if err != nil || len(parsed) != ed25519.PublicKeySize {
		t.Fatalf("base64 key parse = %v, %x", err, parsed)
	}
}

func TestRunRejectsMissingInstallArguments(t *testing.T) {
	if err := run([]string{"install"}, strings.NewReader(""), &strings.Builder{}); err == nil {
		t.Fatal("install without bundle/root/key was accepted")
	}
}
