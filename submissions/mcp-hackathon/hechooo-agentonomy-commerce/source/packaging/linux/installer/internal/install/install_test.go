package install_test

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/ed25519"
	"encoding/base64"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/HEchooo/Clink/packaging/linux/installer/internal/archive"
	"github.com/HEchooo/Clink/packaging/linux/installer/internal/install"
)

func validBundle(t *testing.T, version string, payload []byte) *archive.Bundle {
	t.Helper()
	private := ed25519.NewKeyFromSeed(make([]byte, ed25519.SeedSize))
	license := []byte("operator license")
	notice := []byte("operator notice")
	metadata := map[string]any{
		"created_at": "2023-11-14T22:13:20Z",
		"entrypoint": "payload/bin/clink-launcher",
		"files": []any{
			map[string]any{
				"mode":   "0755",
				"path":   "payload/bin/clink-launcher",
				"sha256": archive.SHA256Hex(payload),
				"size":   len(payload),
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
		},
		"platform":          "linux-x86_64",
		"schema_version":    1,
		"source_date_epoch": 1700000000,
		"version":           version,
	}
	metadataBytes, err := archive.CanonicalJSON(metadata)
	if err != nil {
		t.Fatalf("canonical metadata: %v", err)
	}
	var raw bytes.Buffer
	zipped := gzip.NewWriter(&raw)
	tarWriter := tar.NewWriter(zipped)
	for _, current := range []struct {
		name string
		mode int64
		data []byte
	}{
		{name: "release-metadata.json", mode: 0644, data: metadataBytes},
		{name: "release-signature.ed25519", mode: 0644, data: []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, metadataBytes)) + "\n")},
		{name: "payload/bin/clink-launcher", mode: 0755, data: payload},
		{name: "payload/LICENSE", mode: 0644, data: license},
		{name: "payload/NOTICE", mode: 0644, data: notice},
	} {
		if err := tarWriter.WriteHeader(&tar.Header{
			Name: current.name, Mode: current.mode, Size: int64(len(current.data)), Typeflag: tar.TypeReg,
		}); err != nil {
			t.Fatalf("write tar header: %v", err)
		}
		if _, err := tarWriter.Write(current.data); err != nil {
			t.Fatalf("write tar member: %v", err)
		}
	}
	if err := tarWriter.Close(); err != nil {
		t.Fatalf("close tar: %v", err)
	}
	if err := zipped.Close(); err != nil {
		t.Fatalf("close gzip: %v", err)
	}
	archiveBytes := bytes.NewReader(raw.Bytes())
	bundle, err := archive.Verify(archiveBytes, private.Public().(ed25519.PublicKey))
	if err != nil {
		t.Fatalf("verify bundle: %v", err)
	}
	return bundle
}

func TestInstallSwitchesCurrentAtomicallyAndIsIdempotent(t *testing.T) {
	root := privateRoot(t)
	first := validBundle(t, "1.0.0", []byte("one"))
	result, err := install.Install(root, first)
	first.Close()
	if err != nil {
		t.Fatalf("install first version: %v", err)
	}
	if !result.Changed {
		t.Fatal("first install was not reported as changed")
	}
	assertCurrent(t, root, "1.0.0", "one")

	second := validBundle(t, "1.0.0", []byte("one"))
	result, err = install.Install(root, second)
	second.Close()
	if err != nil {
		t.Fatalf("repeat install: %v", err)
	}
	if result.Changed {
		t.Fatal("same-version install was not idempotent")
	}
	assertCurrent(t, root, "1.0.0", "one")
}

func TestInstallRejectsExistingRootWithoutPrivatePermissions(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0o755); err != nil {
		t.Fatalf("make root permissive: %v", err)
	}
	bundle := validBundle(t, "1.0.0", []byte("one"))
	defer bundle.Close()
	if _, err := install.Install(root, bundle); err == nil {
		t.Fatal("installer accepted a root without mode 0700")
	}
}

func TestInstallRejectsRootOwnedByAnotherUID(t *testing.T) {
	root := privateRoot(t)
	makeForeignOwner(t, root)
	bundle := validBundle(t, "1.0.0", []byte("one"))
	defer bundle.Close()
	if _, err := install.Install(root, bundle); err == nil {
		t.Fatal("installer accepted a root owned by another UID")
	}
}

func TestInstallRejectsUnsafePreexistingLock(t *testing.T) {
	tests := []struct {
		name  string
		setup func(t *testing.T, root, lockPath string)
	}{
		{
			name: "symlink",
			setup: func(t *testing.T, root, lockPath string) {
				target := filepath.Join(t.TempDir(), "lock-target")
				if err := os.WriteFile(target, nil, 0o600); err != nil {
					t.Fatalf("create lock target: %v", err)
				}
				if err := os.Symlink(target, lockPath); err != nil {
					t.Fatalf("create lock symlink: %v", err)
				}
			},
		},
		{
			name: "hardlink",
			setup: func(t *testing.T, root, lockPath string) {
				if err := os.WriteFile(lockPath, nil, 0o600); err != nil {
					t.Fatalf("create lock: %v", err)
				}
				if err := os.Link(lockPath, filepath.Join(root, "lock-alias")); err != nil {
					t.Fatalf("create lock hardlink: %v", err)
				}
			},
		},
		{
			name: "permissive-mode",
			setup: func(t *testing.T, root, lockPath string) {
				if err := os.WriteFile(lockPath, nil, 0o644); err != nil {
					t.Fatalf("create permissive lock: %v", err)
				}
			},
		},
	}
	for _, current := range tests {
		t.Run(current.name, func(t *testing.T) {
			root := privateRoot(t)
			lockPath := filepath.Join(root, ".install.lock")
			current.setup(t, root, lockPath)
			bundle := validBundle(t, "1.0.0", []byte("one"))
			defer bundle.Close()
			if _, err := install.Install(root, bundle); err == nil {
				t.Fatal("installer accepted an unsafe preexisting lock")
			}
		})
	}
}

func TestInstallRejectsLockOwnedByAnotherUID(t *testing.T) {
	root := privateRoot(t)
	lockPath := filepath.Join(root, ".install.lock")
	if err := os.WriteFile(lockPath, nil, 0o600); err != nil {
		t.Fatalf("create lock: %v", err)
	}
	makeForeignOwner(t, lockPath)
	bundle := validBundle(t, "1.0.0", []byte("one"))
	defer bundle.Close()
	if _, err := install.Install(root, bundle); err == nil {
		t.Fatal("installer accepted a lock owned by another UID")
	}
}

func TestInstallKeepsPreviousCurrentOnSameVersionConflict(t *testing.T) {
	root := privateRoot(t)
	first := validBundle(t, "1.0.0", []byte("one"))
	if _, err := install.Install(root, first); err != nil {
		t.Fatalf("install first version: %v", err)
	}
	first.Close()
	conflict := validBundle(t, "1.0.0", []byte("different"))
	_, err := install.Install(root, conflict)
	conflict.Close()
	if err == nil || !strings.Contains(err.Error(), "different content") {
		t.Fatalf("conflict error = %v", err)
	}
	assertCurrent(t, root, "1.0.0", "one")
}

func TestRollbackSwitchesToPreviousVersionAndCanBeRepeated(t *testing.T) {
	root := privateRoot(t)
	first := validBundle(t, "1.0.0", []byte("one"))
	if _, err := install.Install(root, first); err != nil {
		t.Fatalf("install first version: %v", err)
	}
	first.Close()
	second := validBundle(t, "2.0.0", []byte("two"))
	if _, err := install.Install(root, second); err != nil {
		t.Fatalf("install second version: %v", err)
	}
	second.Close()
	if _, err := install.Rollback(root); err != nil {
		t.Fatalf("rollback: %v", err)
	}
	assertCurrent(t, root, "1.0.0", "one")
	if _, err := install.Rollback(root); err != nil {
		t.Fatalf("rollback toggle: %v", err)
	}
	assertCurrent(t, root, "2.0.0", "two")
}

func TestRollbackRejectsSymlinkedPreviousVersion(t *testing.T) {
	root := privateRoot(t)
	first := validBundle(t, "1.0.0", []byte("one"))
	if _, err := install.Install(root, first); err != nil {
		t.Fatalf("install first version: %v", err)
	}
	first.Close()
	second := validBundle(t, "2.0.0", []byte("two"))
	if _, err := install.Install(root, second); err != nil {
		t.Fatalf("install second version: %v", err)
	}
	second.Close()

	versions := filepath.Join(root, "versions")
	if err := os.RemoveAll(filepath.Join(versions, "1.0.0")); err != nil {
		t.Fatalf("remove previous version: %v", err)
	}
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(versions, "1.0.0")); err != nil {
		t.Fatalf("create malicious version link: %v", err)
	}
	if _, err := install.Rollback(root); err == nil {
		t.Fatal("rollback accepted a symlinked previous version")
	}
	assertCurrent(t, root, "2.0.0", "two")
}

func assertCurrent(t *testing.T, root, version, content string) {
	t.Helper()
	current, err := filepath.EvalSymlinks(filepath.Join(root, "current"))
	if err != nil {
		t.Fatalf("resolve current: %v", err)
	}
	if filepath.Base(current) != version {
		t.Fatalf("current = %q, want %q", current, version)
	}
	data, err := os.ReadFile(filepath.Join(current, "payload/bin/clink-launcher"))
	if err != nil {
		t.Fatalf("read installed payload: %v", err)
	}
	if string(data) != content {
		t.Fatalf("payload = %q, want %q", data, content)
	}
}

func privateRoot(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.Chmod(root, 0o700); err != nil {
		t.Fatalf("make install root private: %v", err)
	}
	return root
}

func makeForeignOwner(t *testing.T, path string) {
	t.Helper()
	current := os.Geteuid()
	foreign := current + 1
	if foreign == current || foreign < 0 {
		foreign = 1
		if foreign == current {
			foreign = 2
		}
	}
	if err := os.Chown(path, foreign, -1); err != nil {
		t.Skipf("cannot set foreign owner for security test: %v", err)
	}
}
