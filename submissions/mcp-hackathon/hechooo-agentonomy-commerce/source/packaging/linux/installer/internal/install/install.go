// Package install performs verified, versioned, atomic release installation.
package install

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/HEchooo/Clink/packaging/linux/installer/internal/archive"
	"github.com/HEchooo/Clink/packaging/linux/installer/internal/upgrade"
)

// Result describes the selected version after an install or rollback.
type Result struct {
	Version     string
	Changed     bool
	CurrentPath string
}

// Install installs a verified bundle below root/versions and atomically points
// root/current at its version. A byte-for-byte matching version is idempotent;
// a same-version bundle with different content is rejected.
func Install(root string, bundle *archive.Bundle) (Result, error) {
	if bundle == nil {
		return Result{}, errors.New("verified release bundle is missing")
	}
	if bundle.Metadata.Version == "" {
		return Result{}, errors.New("release version is missing")
	}
	if err := ensureRoot(root); err != nil {
		return Result{}, err
	}
	manager := upgrade.NewManager(root)
	result, err := manager.Install(
		bundle.Metadata.Version,
		func(staging string) error {
			return materializeBundle(staging, bundle)
		},
		func(versionPath string) error {
			return validateInstalledVersion(versionPath, bundle)
		},
	)
	if err != nil {
		return Result{}, err
	}
	return Result{
		Version:     result.Version,
		Changed:     result.Changed,
		CurrentPath: result.CurrentPath,
	}, nil
}

// Rollback atomically swaps current and previous. The previous link is only
// created by a successful switch, so an absent link fails closed.
func Rollback(root string) (Result, error) {
	if err := ensureRoot(root); err != nil {
		return Result{}, err
	}
	result, err := upgrade.NewManager(root).Rollback()
	if err != nil {
		return Result{}, err
	}
	return Result{
		Version:     result.Version,
		Changed:     result.Changed,
		CurrentPath: result.CurrentPath,
	}, nil
}

func materializeBundle(staging string, bundle *archive.Bundle) error {
	if err := os.Chmod(staging, 0o755); err != nil {
		return fmt.Errorf("secure release staging directory: %w", err)
	}
	if err := writeRegularFile(filepath.Join(staging, archive.MetadataName), bundle.MetadataBytes, 0o644); err != nil {
		return fmt.Errorf("write release metadata: %w", err)
	}
	if err := writeRegularFile(filepath.Join(staging, archive.SignatureName), append(append([]byte(nil), bundle.Signature...), '\n'), 0o644); err != nil {
		return fmt.Errorf("write release signature: %w", err)
	}
	for _, entry := range bundle.Entries {
		if !strings.HasPrefix(entry.Path, archive.PayloadPrefix) {
			return errors.New("verified payload path is outside payload")
		}
		destination := filepath.Join(staging, filepath.FromSlash(entry.Path))
		if err := ensureParentDirectories(staging, destination); err != nil {
			return err
		}
		input, err := entry.Open()
		if err != nil {
			return fmt.Errorf("open verified payload: %w", err)
		}
		copyErr := copyRegularFile(destination, input, entry.Size, entry.Mode.Perm())
		closeErr := input.Close()
		if copyErr != nil {
			return fmt.Errorf("write verified payload %s: %w", entry.Path, copyErr)
		}
		if closeErr != nil {
			return fmt.Errorf("close verified payload %s: %w", entry.Path, closeErr)
		}
	}
	if err := syncDirectoryTree(staging); err != nil {
		return err
	}
	return nil
}

func validateInstalledVersion(versionPath string, bundle *archive.Bundle) error {
	expectedFiles := map[string]bool{
		archive.MetadataName:  true,
		archive.SignatureName: true,
	}
	for _, entry := range bundle.Entries {
		expectedFiles[filepath.FromSlash(entry.Path)] = true
	}
	err := filepath.WalkDir(versionPath, func(name string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if name == versionPath {
			return nil
		}
		relative, err := filepath.Rel(versionPath, name)
		if err != nil {
			return err
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return errors.New("installed path contains a symlink")
		}
		if entry.IsDir() {
			return nil
		}
		if !entry.Type().IsRegular() || !expectedFiles[relative] {
			return errors.New("installed version contains an unsigned file")
		}
		delete(expectedFiles, relative)
		return nil
	})
	if err != nil || len(expectedFiles) != 0 {
		return errors.New("different content")
	}
	if err := ensureRegularPath(versionPath, filepath.Join(versionPath, archive.MetadataName)); err != nil {
		return errors.New("different content")
	}
	metadata, err := os.ReadFile(filepath.Join(versionPath, archive.MetadataName))
	if err != nil || !bytes.Equal(metadata, bundle.MetadataBytes) {
		return errors.New("different content")
	}
	if err := ensureRegularPath(versionPath, filepath.Join(versionPath, archive.SignatureName)); err != nil {
		return errors.New("different content")
	}
	signature, err := os.ReadFile(filepath.Join(versionPath, archive.SignatureName))
	if err != nil || !bytes.Equal(bytes.TrimSpace(signature), bytes.TrimSpace(bundle.Signature)) {
		return errors.New("different content")
	}
	for _, entry := range bundle.Entries {
		filePath := filepath.Join(versionPath, filepath.FromSlash(entry.Path))
		if err := ensureRegularPath(versionPath, filePath); err != nil {
			return errors.New("different content")
		}
		info, err := os.Stat(filePath)
		if err != nil || info.Size() != entry.Size || info.Mode().Perm() != entry.Mode.Perm() {
			return errors.New("different content")
		}
		digest, err := fileDigest(filePath)
		if err != nil || digest != entry.SHA256 {
			return errors.New("different content")
		}
	}
	return nil
}

func ensureRoot(root string) error {
	if root == "" {
		return errors.New("install root is missing")
	}
	info, err := os.Lstat(root)
	if errors.Is(err, os.ErrNotExist) {
		if err := os.MkdirAll(root, 0o700); err != nil {
			return err
		}
		info, err = os.Lstat(root)
	}
	if err != nil {
		return fmt.Errorf("inspect install root: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("install root must be a directory, not a symlink")
	}
	if info.Mode().Perm() != 0o700 || !ownedByCurrentUser(info) {
		return errors.New("install root must be private and owned by the current UID")
	}
	return nil
}

func ownedByCurrentUser(info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && uint64(stat.Uid) == uint64(os.Geteuid())
}

func ensureParentDirectories(base, destination string) error {
	relative, err := filepath.Rel(base, filepath.Dir(destination))
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(os.PathSeparator)) {
		return errors.New("payload path escapes staging directory")
	}
	current := base
	if relative != "." {
		for _, part := range strings.Split(relative, string(os.PathSeparator)) {
			if part == "" || part == "." {
				continue
			}
			current = filepath.Join(current, part)
			info, statErr := os.Lstat(current)
			switch {
			case errors.Is(statErr, os.ErrNotExist):
				if err := os.Mkdir(current, 0o755); err != nil {
					return err
				}
			case statErr != nil:
				return statErr
			case info.Mode()&os.ModeSymlink != 0 || !info.IsDir():
				return errors.New("payload parent is not a directory")
			}
		}
	}
	return nil
}

func writeRegularFile(name string, data []byte, mode os.FileMode) error {
	file, err := os.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		return err
	}
	if _, err := file.Write(data); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return err
	}
	return file.Close()
}

func copyRegularFile(name string, input *os.File, size int64, mode os.FileMode) error {
	file, err := os.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		return err
	}
	written, copyErr := io.CopyN(file, input, size)
	if copyErr == nil && written != size {
		copyErr = errors.New("payload size changed during install")
	}
	if copyErr == nil {
		var extra [1]byte
		if count, readErr := input.Read(extra[:]); count != 0 || (readErr != io.EOF && readErr != nil) {
			copyErr = errors.New("payload contains trailing bytes")
		}
	}
	if copyErr == nil {
		copyErr = file.Sync()
	}
	closeErr := file.Close()
	if copyErr != nil {
		_ = os.Remove(name)
		return copyErr
	}
	return closeErr
}

func ensureRegularPath(base, name string) error {
	relative, err := filepath.Rel(base, name)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(os.PathSeparator)) {
		return errors.New("installed path escapes version")
	}
	current := base
	for _, part := range strings.Split(relative, string(os.PathSeparator)) {
		if part == "" || part == "." {
			continue
		}
		current = filepath.Join(current, part)
		info, err := os.Lstat(current)
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return errors.New("installed path contains a symlink")
		}
		if current != name && !info.IsDir() {
			return errors.New("installed parent is not a directory")
		}
	}
	return nil
}

func fileDigest(name string) (string, error) {
	file, err := os.Open(name)
	if err != nil {
		return "", err
	}
	defer file.Close()
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

func syncDirectoryTree(root string) error {
	entries, err := os.ReadDir(root)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		path := filepath.Join(root, entry.Name())
		if entry.IsDir() {
			if err := syncDirectoryTree(path); err != nil {
				return err
			}
		}
	}
	return syncDirectory(root)
}

func syncDirectory(name string) error {
	directory, err := os.Open(name)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}
