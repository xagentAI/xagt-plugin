package upgrade_test

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/HEchooo/Clink/packaging/linux/installer/internal/upgrade"
)

func TestUpgradeSwitchesCurrentAtomicallyAndRollsBackExplicitly(t *testing.T) {
	root := t.TempDir()
	manager := upgrade.NewManager(root)
	if _, err := manager.Upgrade("1.0.0", writeVersion("one")); err != nil {
		t.Fatalf("first upgrade: %v", err)
	}
	if _, err := manager.Upgrade("2.0.0", writeVersion("two")); err != nil {
		t.Fatalf("second upgrade: %v", err)
	}
	assertCurrent(t, root, "2.0.0", "two")
	if _, err := manager.Rollback(); err != nil {
		t.Fatalf("rollback: %v", err)
	}
	assertCurrent(t, root, "1.0.0", "one")
}

func TestManagerInstallValidatesExistingVersionBeforeSelectingIt(t *testing.T) {
	root := t.TempDir()
	manager := upgrade.NewManager(root)
	validate := func(expected string) func(string) error {
		return func(versionPath string) error {
			payload, err := os.ReadFile(filepath.Join(versionPath, "payload", "version.txt"))
			if err != nil {
				return err
			}
			if string(payload) != expected {
				return errors.New("installed version has different content")
			}
			return nil
		}
	}

	if _, err := manager.Install("1.0.0", writeVersion("one"), validate("one")); err != nil {
		t.Fatalf("install first version: %v", err)
	}
	if _, err := manager.Install("2.0.0", writeVersion("two"), validate("two")); err != nil {
		t.Fatalf("install second version: %v", err)
	}
	if _, err := manager.Install("2.0.0", writeVersion("different"), validate("different")); err == nil || !strings.Contains(err.Error(), "different content") {
		t.Fatalf("same-version conflict error = %v", err)
	}
	assertCurrent(t, root, "2.0.0", "two")
}

func TestUpgradeJournalIsAppendOnlyHashLinked(t *testing.T) {
	root := t.TempDir()
	manager := upgrade.NewManager(root)
	if _, err := manager.Upgrade("1.0.0", writeVersion("one")); err != nil {
		t.Fatalf("upgrade: %v", err)
	}
	if _, err := manager.Upgrade("2.0.0", writeVersion("two")); err != nil {
		t.Fatalf("upgrade: %v", err)
	}
	entries, err := manager.ReadJournal()
	if err != nil {
		t.Fatalf("read journal: %v", err)
	}
	if len(entries) < 4 {
		t.Fatalf("journal entries = %d, want mutation boundaries", len(entries))
	}
	previous := ""
	for _, entry := range entries {
		if entry.PrevHash != previous {
			t.Fatalf("entry %d prev hash = %q, want %q", entry.Seq, entry.PrevHash, previous)
		}
		if entry.Hash == "" {
			t.Fatalf("entry %d has no hash", entry.Seq)
		}
		previous = entry.Hash
	}
	journal := filepath.Join(root, "upgrade.journal")
	raw, err := os.ReadFile(journal)
	if err != nil {
		t.Fatalf("read journal bytes: %v", err)
	}
	if err := os.WriteFile(journal, append(raw, []byte("tampered\n")...), 0o600); err != nil {
		t.Fatalf("tamper journal: %v", err)
	}
	if err := manager.Recover(); err == nil || !strings.Contains(err.Error(), "journal") {
		t.Fatalf("tampered journal recovery error = %v", err)
	}
}

func TestUpgradeRecoversEveryInjectedMutationBoundary(t *testing.T) {
	boundaries := []upgrade.Boundary{
		upgrade.BeforeStage,
		upgrade.AfterStage,
		upgrade.BeforePublish,
		upgrade.AfterPublish,
		upgrade.BeforeSwitch,
		upgrade.AfterSwitch,
	}
	for _, boundary := range boundaries {
		t.Run(string(boundary), func(t *testing.T) {
			root := t.TempDir()
			baseline := upgrade.NewManager(root)
			if _, err := baseline.Upgrade("1.0.0", writeVersion("one")); err != nil {
				t.Fatalf("baseline: %v", err)
			}
			manager := upgrade.NewManager(root, upgrade.WithFaultInjector(func(current upgrade.Boundary) error {
				if current == boundary {
					return errors.New("injected crash")
				}
				return nil
			}))
			_, _ = manager.Upgrade("2.0.0", writeVersion("two"))
			recovered := upgrade.NewManager(root)
			if err := recovered.Recover(); err != nil {
				t.Fatalf("recover %s: %v", boundary, err)
			}
			current, err := recovered.CurrentVersion()
			if err != nil {
				t.Fatalf("current after recover: %v", err)
			}
			if current != "1.0.0" && current != "2.0.0" {
				t.Fatalf("current after recover = %q", current)
			}
			if _, err := recovered.Upgrade("2.0.0", writeVersion("two")); err != nil {
				t.Fatalf("retry after recover %s: %v", boundary, err)
			}
		})
	}
}

func writeVersion(content string) upgrade.PrepareFunc {
	return func(staging string) error {
		path := filepath.Join(staging, "payload", "version.txt")
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return err
		}
		return os.WriteFile(path, []byte(content), 0o644)
	}
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
	raw, err := os.ReadFile(filepath.Join(current, "payload", "version.txt"))
	if err != nil {
		t.Fatalf("read current version: %v", err)
	}
	if string(raw) != content {
		t.Fatalf("current payload = %q, want %q", raw, content)
	}
}
