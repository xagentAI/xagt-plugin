// Command clink-installer verifies and installs signed Clink Linux releases.
// It has no dependency on Python, a shell extractor, or the release payload.
package main

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/HEchooo/Clink/packaging/linux/installer/internal/archive"
	"github.com/HEchooo/Clink/packaging/linux/installer/internal/install"
)

func main() {
	if err := run(os.Args[1:], os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "clink-installer:", err)
		os.Exit(1)
	}
}

func run(arguments []string, input io.Reader, output io.Writer) error {
	_ = input
	if len(arguments) == 0 {
		return errors.New("command is required: install, verify, or rollback")
	}
	switch arguments[0] {
	case "install":
		flags := flag.NewFlagSet("install", flag.ContinueOnError)
		flags.SetOutput(io.Discard)
		bundlePath := flags.String("bundle", "", "signed .tar.gz bundle")
		root := flags.String("root", "", "installation root")
		publicKey := flags.String("public-key", "", "Ed25519 public key as hex or base64")
		publicKeyFile := flags.String("public-key-file", "", "file containing an Ed25519 public key")
		if err := flags.Parse(arguments[1:]); err != nil {
			return errors.New("invalid install arguments")
		}
		if *bundlePath == "" || *root == "" {
			return errors.New("install requires --bundle and --root")
		}
		key, err := parsePublicKey(*publicKey, *publicKeyFile)
		if err != nil {
			return err
		}
		bundle, err := verifyBundleFile(*bundlePath, key)
		if err != nil {
			return err
		}
		defer bundle.Close()
		result, err := install.Install(*root, bundle)
		if err != nil {
			return err
		}
		_, _ = fmt.Fprintf(output, "installed version=%s changed=%t\n", result.Version, result.Changed)
		return nil
	case "verify":
		flags := flag.NewFlagSet("verify", flag.ContinueOnError)
		flags.SetOutput(io.Discard)
		bundlePath := flags.String("bundle", "", "signed .tar.gz bundle")
		publicKey := flags.String("public-key", "", "Ed25519 public key as hex or base64")
		publicKeyFile := flags.String("public-key-file", "", "file containing an Ed25519 public key")
		if err := flags.Parse(arguments[1:]); err != nil {
			return errors.New("invalid verify arguments")
		}
		if *bundlePath == "" {
			return errors.New("verify requires --bundle")
		}
		key, err := parsePublicKey(*publicKey, *publicKeyFile)
		if err != nil {
			return err
		}
		bundle, err := verifyBundleFile(*bundlePath, key)
		if err != nil {
			return err
		}
		defer bundle.Close()
		_, _ = fmt.Fprintf(output, "verified version=%s platform=%s\n", bundle.Metadata.Version, bundle.Metadata.Platform)
		return nil
	case "rollback":
		flags := flag.NewFlagSet("rollback", flag.ContinueOnError)
		flags.SetOutput(io.Discard)
		root := flags.String("root", "", "installation root")
		if err := flags.Parse(arguments[1:]); err != nil {
			return errors.New("invalid rollback arguments")
		}
		if *root == "" {
			return errors.New("rollback requires --root")
		}
		result, err := install.Rollback(*root)
		if err != nil {
			return err
		}
		_, _ = fmt.Fprintf(output, "rolled back version=%s\n", result.Version)
		return nil
	default:
		return errors.New("unknown command")
	}
}

func verifyBundleFile(name string, publicKey ed25519.PublicKey) (*archive.Bundle, error) {
	info, err := os.Lstat(name)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return nil, errors.New("bundle must be a regular file")
	}
	file, err := os.Open(name)
	if err != nil {
		return nil, errors.New("cannot open bundle")
	}
	bundle, verifyErr := archive.Verify(file, publicKey)
	closeErr := file.Close()
	if verifyErr != nil {
		return nil, verifyErr
	}
	if closeErr != nil {
		_ = bundle.Close()
		return nil, errors.New("cannot close bundle")
	}
	return bundle, nil
}

func parsePublicKey(value, filename string) (ed25519.PublicKey, error) {
	if value != "" && filename != "" {
		return nil, errors.New("choose one public key source")
	}
	var raw []byte
	if filename != "" {
		info, err := os.Lstat(filename)
		if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return nil, errors.New("public key file must be a regular file")
		}
		data, err := os.ReadFile(filename)
		if err != nil {
			return nil, errors.New("cannot read public key file")
		}
		raw = bytes.TrimSpace(data)
	} else {
		raw = []byte(strings.TrimSpace(value))
	}
	if len(raw) == ed25519.PublicKeySize {
		return ed25519.PublicKey(append([]byte(nil), raw...)), nil
	}
	text := string(raw)
	if strings.HasPrefix(text, "0x") {
		text = text[2:]
	}
	if len(text) == ed25519.PublicKeySize*2 {
		decoded, err := hex.DecodeString(text)
		if err == nil {
			return ed25519.PublicKey(decoded), nil
		}
	}
	for _, encoding := range []*base64.Encoding{base64.StdEncoding, base64.RawStdEncoding, base64.URLEncoding, base64.RawURLEncoding} {
		decoded, err := encoding.DecodeString(text)
		if err == nil && len(decoded) == ed25519.PublicKeySize {
			return ed25519.PublicKey(decoded), nil
		}
	}
	return nil, errors.New("public key must be 32-byte hex or base64")
}
