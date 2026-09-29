// Package upgrade owns the crash-recoverable release switch journal around a
// verified/prepared release. Archive verification remains in internal/install
// and both paths share its install lock; this package adds no second archive
// or signature validation path.
package upgrade

import (
	"bufio"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

const (
	versionsDirectory = "versions"
	currentName       = "current"
	previousName      = "previous"
	journalName       = "upgrade.journal"
	// Share the installer lock so upgrade journaling cannot race the signed
	// archive install/rollback implementation.
	lockName = ".install.lock"
)

// Boundary identifies a mutation boundary at which a process may fail.
type Boundary string

const (
	BeforeStage   Boundary = "before_stage"
	AfterStage    Boundary = "after_stage"
	BeforePublish Boundary = "before_publish"
	AfterPublish  Boundary = "after_publish"
	BeforeSwitch  Boundary = "before_switch"
	AfterSwitch   Boundary = "after_switch"
)

// PrepareFunc populates a version's staging directory.
type PrepareFunc func(staging string) error

// FaultInjector is used by tests to stop an operation at a mutation boundary.
type FaultInjector func(Boundary) error

type option struct{ fault FaultInjector }

// Option configures a Manager. It is intentionally small so production code
// cannot accidentally make the release switch non-atomic.
type Option func(*option)

// WithFaultInjector installs a fault injector for recovery tests.
func WithFaultInjector(injector FaultInjector) Option {
	return func(value *option) { value.fault = injector }
}

// Result describes the release selected by an operation.
type Result struct {
	Version     string
	Changed     bool
	CurrentPath string
}

// JournalEntry is one immutable hash-linked journal record.
type JournalEntry struct {
	Seq       uint64 `json:"seq"`
	Operation string `json:"operation"`
	Phase     string `json:"phase"`
	Version   string `json:"version"`
	Previous  string `json:"previous,omitempty"`
	Staging   string `json:"staging,omitempty"`
	PrevHash  string `json:"prev_hash"`
	Hash      string `json:"hash"`
}

// Manager performs version staging and atomic current/previous switching.
type Manager struct {
	root    string
	options option
}

// NewManager returns a release manager rooted at root.
func NewManager(root string, options ...Option) *Manager {
	configured := option{}
	for _, apply := range options {
		if apply != nil {
			apply(&configured)
		}
	}
	return &Manager{root: filepath.Clean(root), options: configured}
}

// Upgrade stages a version, publishes it, and atomically selects it.
func (m *Manager) Upgrade(version string, prepare PrepareFunc) (Result, error) {
	return m.selectPrepared("upgrade", version, prepare, nil, false)
}

// Install selects a verified/materialized version and atomically updates the
// current/previous links. Existing versions must be validated by the caller;
// this keeps bundle-specific validation in internal/install while retaining a
// single crash-recoverable release switch implementation here.
func (m *Manager) Install(
	version string,
	prepare PrepareFunc,
	validate func(string) error,
) (Result, error) {
	if validate == nil {
		return Result{}, errors.New("install validation function is missing")
	}
	return m.selectPrepared("install", version, prepare, validate, true)
}

func (m *Manager) selectPrepared(
	operation string,
	version string,
	prepare PrepareFunc,
	validate func(string) error,
	allowExisting bool,
) (Result, error) {
	if err := validateVersion(version); err != nil {
		return Result{}, err
	}
	if prepare == nil {
		return Result{}, fmt.Errorf("%s prepare function is missing", operation)
	}
	if err := m.ensureLayout(); err != nil {
		return Result{}, err
	}
	lock, err := m.acquireLock()
	if err != nil {
		return Result{}, err
	}
	defer lock.Close()
	if err := m.recoverLocked(); err != nil {
		return Result{}, err
	}
	current, err := m.currentVersionLocked()
	if err != nil {
		return Result{}, err
	}
	versionPath := filepath.Join(m.root, versionsDirectory, version)
	info, statErr := os.Lstat(versionPath)
	existing := statErr == nil
	if statErr != nil && !errors.Is(statErr, os.ErrNotExist) {
		return Result{}, fmt.Errorf("inspect %s version: %w", operation, statErr)
	}
	if existing {
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return Result{}, errors.New("existing release version is not a directory")
		}
		if allowExisting {
			if err := validate(versionPath); err != nil {
				return Result{}, fmt.Errorf("same-version release has different content: %w", err)
			}
		} else if current != version {
			return Result{}, errors.New("upgrade version already exists")
		}
	}
	if current == version {
		return m.result(version, false), nil
	}

	if !existing {
		staging, err := stagingPath(m.root)
		if err != nil {
			return Result{}, fmt.Errorf("create %s staging: %w", operation, err)
		}
		stagingName := filepath.Base(staging)
		removeStaging := true
		defer func() {
			if removeStaging {
				_ = safeRemoveStaging(m.root, staging)
			}
		}()

		if err := m.appendJournal(operation, "started", version, current, stagingName); err != nil {
			return Result{}, err
		}
		if err := m.fault(BeforeStage); err != nil {
			return Result{}, err
		}
		if err := os.Mkdir(staging, 0o755); err != nil {
			return Result{}, fmt.Errorf("create %s staging: %w", operation, err)
		}
		if err := prepare(staging); err != nil {
			return Result{}, fmt.Errorf("prepare %s: %w", operation, err)
		}
		if err := syncTree(staging); err != nil {
			return Result{}, err
		}
		if err := m.appendJournal(operation, "staged", version, current, stagingName); err != nil {
			return Result{}, err
		}
		if err := m.fault(AfterStage); err != nil {
			return Result{}, err
		}
		if err := m.fault(BeforePublish); err != nil {
			return Result{}, err
		}
		if err := os.Rename(staging, versionPath); err != nil {
			return Result{}, fmt.Errorf("publish %s version: %w", operation, err)
		}
		removeStaging = false
		if err := syncDirectory(filepath.Join(m.root, versionsDirectory)); err != nil {
			return Result{}, err
		}
		if err := m.appendJournal(operation, "published", version, current, ""); err != nil {
			return Result{}, err
		}
		if err := m.fault(AfterPublish); err != nil {
			return Result{}, err
		}
	} else if allowExisting {
		if err := m.appendJournal(operation, "started", version, current, ""); err != nil {
			return Result{}, err
		}
	}

	if err := m.fault(BeforeSwitch); err != nil {
		return Result{}, err
	}
	if current != "" {
		if err := atomicSymlink(
			filepath.Join(m.root, previousName),
			filepath.Join(versionsDirectory, current),
		); err != nil {
			return Result{}, fmt.Errorf("preserve previous release: %w", err)
		}
		if err := m.appendJournal(operation, "previous_saved", version, current, ""); err != nil {
			return Result{}, err
		}
	}
	if err := atomicSymlink(
		filepath.Join(m.root, currentName),
		filepath.Join(versionsDirectory, version),
	); err != nil {
		return Result{}, fmt.Errorf("switch current release: %w", err)
	}
	if err := m.appendJournal(operation, "switched", version, current, ""); err != nil {
		return Result{}, err
	}
	if err := m.fault(AfterSwitch); err != nil {
		return Result{}, err
	}
	if err := m.appendJournal(operation, "committed", version, current, ""); err != nil {
		return Result{}, err
	}
	return m.result(version, true), nil
}

// Rollback explicitly swaps current and previous and records the operation.
func (m *Manager) Rollback() (Result, error) {
	if err := m.ensureLayout(); err != nil {
		return Result{}, err
	}
	lock, err := m.acquireLock()
	if err != nil {
		return Result{}, err
	}
	defer lock.Close()
	if err := m.recoverLocked(); err != nil {
		return Result{}, err
	}
	current, err := m.currentVersionLocked()
	if err != nil {
		return Result{}, err
	}
	previous, err := m.linkedVersion(filepath.Join(m.root, previousName))
	if err != nil {
		return Result{}, err
	}
	if previous == "" {
		return Result{}, errors.New("no previous release is available")
	}
	if err := m.appendJournal("rollback", "started", previous, current, ""); err != nil {
		return Result{}, err
	}
	if err := m.fault(BeforeSwitch); err != nil {
		return Result{}, err
	}
	if err := atomicSymlink(
		filepath.Join(m.root, currentName),
		filepath.Join(versionsDirectory, previous),
	); err != nil {
		return Result{}, fmt.Errorf("switch rollback release: %w", err)
	}
	if err := m.appendJournal("rollback", "switched", previous, current, ""); err != nil {
		return Result{}, err
	}
	if err := m.fault(AfterSwitch); err != nil {
		return Result{}, err
	}
	if current != "" {
		if err := atomicSymlink(
			filepath.Join(m.root, previousName),
			filepath.Join(versionsDirectory, current),
		); err != nil {
			return Result{}, fmt.Errorf("preserve rollback release: %w", err)
		}
	}
	if err := m.appendJournal("rollback", "committed", previous, current, ""); err != nil {
		return Result{}, err
	}
	return m.result(previous, true), nil
}

// CurrentVersion returns the version selected by current.
func (m *Manager) CurrentVersion() (string, error) {
	if err := m.ensureLayout(); err != nil {
		return "", err
	}
	return m.currentVersionLocked()
}

// ReadJournal validates and returns every journal entry. Any malformed,
// reordered, or hash-modified record fails closed.
func (m *Manager) ReadJournal() ([]JournalEntry, error) {
	if err := m.ensureRoot(); err != nil {
		return nil, err
	}
	path := filepath.Join(m.root, journalName)
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read upgrade journal: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return nil, errors.New("upgrade journal must be a regular file")
	}
	if info.Mode().Perm() != 0o600 {
		return nil, errors.New("upgrade journal permissions are invalid")
	}
	if stat, ok := info.Sys().(*syscall.Stat_t); ok && uint32(stat.Uid) != uint32(os.Getuid()) {
		return nil, errors.New("upgrade journal owner is invalid")
	}
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, fmt.Errorf("read upgrade journal: %w", err)
	}
	defer file.Close()
	entries := make([]JournalEntry, 0)
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 1024), 1024*1024)
	previousHash := ""
	var expectedSeq uint64 = 1
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(strings.TrimSpace(string(line))) == 0 {
			return nil, errors.New("upgrade journal contains an empty record")
		}
		var entry JournalEntry
		if err := json.Unmarshal(line, &entry); err != nil {
			return nil, fmt.Errorf("upgrade journal is invalid: %w", err)
		}
		if entry.Seq != expectedSeq || entry.PrevHash != previousHash {
			return nil, errors.New("upgrade journal chain is invalid")
		}
		if entry.Hash == "" || entry.Hash != hashEntry(entry) {
			return nil, errors.New("upgrade journal hash is invalid")
		}
		if entry.Operation != "upgrade" && entry.Operation != "install" && entry.Operation != "rollback" && entry.Operation != "recovery" {
			return nil, errors.New("upgrade journal operation is invalid")
		}
		entries = append(entries, entry)
		previousHash = entry.Hash
		expectedSeq++
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read upgrade journal: %w", err)
	}
	return entries, nil
}

// Recover completes or cleans up the last interrupted mutation.
func (m *Manager) Recover() error {
	if err := m.ensureLayout(); err != nil {
		return err
	}
	lock, err := m.acquireLock()
	if err != nil {
		return err
	}
	defer lock.Close()
	return m.recoverLocked()
}

func (m *Manager) recoverLocked() error {
	entries, err := m.ReadJournal()
	if err != nil {
		return err
	}
	if len(entries) == 0 {
		return nil
	}
	last := entries[len(entries)-1]
	if isTerminal(last) {
		return nil
	}
	if last.Operation == "recovery" {
		return nil
	}
	if last.Staging != "" {
		staging := filepath.Join(m.root, versionsDirectory, last.Staging)
		if err := safeRemoveStaging(m.root, staging); err != nil {
			return fmt.Errorf("recover staging: %w", err)
		}
	}
	if last.Phase == "published" || last.Phase == "previous_saved" {
		versionPath := filepath.Join(m.root, versionsDirectory, last.Version)
		info, statErr := os.Lstat(versionPath)
		if statErr != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return errors.New("published release is unavailable during recovery")
		}
		current, currentErr := m.currentVersionLocked()
		if currentErr != nil {
			return currentErr
		}
		if current != last.Version {
			if last.Previous != "" {
				if err := atomicSymlink(
					filepath.Join(m.root, previousName),
					filepath.Join(versionsDirectory, last.Previous),
				); err != nil {
					return fmt.Errorf("recover previous release: %w", err)
				}
			}
			if err := atomicSymlink(
				filepath.Join(m.root, currentName),
				filepath.Join(versionsDirectory, last.Version),
			); err != nil {
				return fmt.Errorf("recover current release: %w", err)
			}
		}
	} else if last.Phase == "switched" {
		// The current link was atomically switched before the journal record;
		// leave that valid release selected.
	}
	return m.appendJournal("recovery", "completed", last.Version, last.Previous, "")
}

func isTerminal(entry JournalEntry) bool {
	return entry.Phase == "committed" || entry.Phase == "recovered"
}

func (m *Manager) appendJournal(
	operation, phase, version, previous, staging string,
) error {
	entries, err := m.ReadJournal()
	if err != nil {
		return err
	}
	entry := JournalEntry{
		Seq:       uint64(len(entries) + 1),
		Operation: operation,
		Phase:     phase,
		Version:   version,
		Previous:  previous,
		Staging:   staging,
	}
	if len(entries) != 0 {
		entry.PrevHash = entries[len(entries)-1].Hash
	}
	entry.Hash = hashEntry(entry)
	payload, err := json.Marshal(entry)
	if err != nil {
		return fmt.Errorf("encode upgrade journal: %w", err)
	}
	path := filepath.Join(m.root, journalName)
	if info, statErr := os.Lstat(path); statErr == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return errors.New("upgrade journal must be a regular file")
		}
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return fmt.Errorf("inspect upgrade journal: %w", statErr)
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_APPEND|syscall.O_NOFOLLOW, 0o600)
	if err != nil {
		return fmt.Errorf("open upgrade journal: %w", err)
	}
	if err := file.Chmod(0o600); err != nil {
		file.Close()
		return fmt.Errorf("secure upgrade journal: %w", err)
	}
	if _, err := file.Write(append(payload, '\n')); err != nil {
		file.Close()
		return fmt.Errorf("append upgrade journal: %w", err)
	}
	if err := file.Sync(); err != nil {
		file.Close()
		return fmt.Errorf("sync upgrade journal: %w", err)
	}
	if err := file.Close(); err != nil {
		return fmt.Errorf("close upgrade journal: %w", err)
	}
	return syncDirectory(m.root)
}

func hashEntry(entry JournalEntry) string {
	entry.Hash = ""
	payload, _ := json.Marshal(entry)
	digest := sha256.Sum256(append([]byte(entry.PrevHash), payload...))
	return hex.EncodeToString(digest[:])
}

func (m *Manager) result(version string, changed bool) Result {
	return Result{
		Version:     version,
		Changed:     changed,
		CurrentPath: filepath.Join(m.root, versionsDirectory, version),
	}
}

func (m *Manager) ensureLayout() error {
	if err := m.ensureRoot(); err != nil {
		return err
	}
	return ensureDirectory(filepath.Join(m.root, versionsDirectory), 0o755)
}

func (m *Manager) ensureRoot() error {
	if m.root == "" || m.root == "." {
		return errors.New("upgrade root is missing")
	}
	info, err := os.Lstat(m.root)
	if errors.Is(err, os.ErrNotExist) {
		if err := os.MkdirAll(m.root, 0o700); err != nil {
			return fmt.Errorf("create upgrade root: %w", err)
		}
		info, err = os.Lstat(m.root)
	}
	if err != nil {
		return fmt.Errorf("inspect upgrade root: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("upgrade root must be a real directory")
	}
	if info.Sys() != nil {
		if stat, ok := info.Sys().(*syscall.Stat_t); ok && uint32(stat.Uid) != uint32(os.Getuid()) {
			return errors.New("upgrade root owner is invalid")
		}
	}
	return nil
}

func ensureDirectory(path string, mode os.FileMode) error {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		if err := os.Mkdir(path, mode); err != nil {
			return fmt.Errorf("create upgrade directory: %w", err)
		}
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect upgrade directory: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("upgrade directory must be a real directory")
	}
	return nil
}

func (m *Manager) acquireLock() (*os.File, error) {
	path := filepath.Join(m.root, lockName)
	info, err := os.Lstat(path)
	if err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return nil, errors.New("upgrade lock must be a regular file")
		}
		if info.Mode().Perm() != 0o600 || !ownedByCurrentUser(info) || !singleLink(info) {
			return nil, errors.New("upgrade lock must be a regular, private, single-link file owned by the current UID")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("inspect upgrade lock: %w", err)
	}
	file, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|syscall.O_NOFOLLOW, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open upgrade lock: %w", err)
	}
	if err := file.Chmod(0o600); err != nil {
		file.Close()
		return nil, fmt.Errorf("secure upgrade lock: %w", err)
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX); err != nil {
		file.Close()
		return nil, fmt.Errorf("lock upgrade root: %w", err)
	}
	return file, nil
}

func ownedByCurrentUser(info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && uint64(stat.Uid) == uint64(os.Geteuid())
}

func singleLink(info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && uint64(stat.Nlink) == 1
}

func (m *Manager) currentVersionLocked() (string, error) {
	return m.linkedVersion(filepath.Join(m.root, currentName))
}

func (m *Manager) linkedVersion(link string) (string, error) {
	info, err := os.Lstat(link)
	if errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("inspect release link: %w", err)
	}
	if info.Mode()&os.ModeSymlink == 0 {
		return "", errors.New("release selector must be a symlink")
	}
	target, err := os.Readlink(link)
	if err != nil {
		return "", fmt.Errorf("read release link: %w", err)
	}
	prefix := versionsDirectory + string(os.PathSeparator)
	if !strings.HasPrefix(target, prefix) {
		return "", errors.New("release link points outside versions")
	}
	version := filepath.Clean(strings.TrimPrefix(target, prefix))
	if err := validateVersion(version); err != nil {
		return "", errors.New("release link version is invalid")
	}
	versionInfo, err := os.Lstat(filepath.Join(m.root, versionsDirectory, version))
	if err != nil || versionInfo.Mode()&os.ModeSymlink != 0 || !versionInfo.IsDir() {
		return "", errors.New("release link target is unavailable")
	}
	return version, nil
}

func validateVersion(version string) error {
	if version == "" || version == "." || version == ".." ||
		filepath.Base(version) != version || strings.ContainsAny(version, `/\\`) {
		return errors.New("release version is invalid")
	}
	return nil
}

func (m *Manager) fault(boundary Boundary) error {
	if m.options.fault == nil {
		return nil
	}
	if err := m.options.fault(boundary); err != nil {
		return fmt.Errorf("upgrade interrupted at %s: %w", boundary, err)
	}
	return nil
}

func stagingPath(root string) (string, error) {
	versions := filepath.Join(root, versionsDirectory)
	for attempt := 0; attempt < 8; attempt++ {
		randomBytes := make([]byte, 12)
		if _, err := rand.Read(randomBytes); err != nil {
			return "", fmt.Errorf("create staging nonce: %w", err)
		}
		candidate := filepath.Join(
			versions,
			fmt.Sprintf(".staging-%d-%s", os.Getpid(), hex.EncodeToString(randomBytes)),
		)
		if _, err := os.Lstat(candidate); errors.Is(err, os.ErrNotExist) {
			return candidate, nil
		} else if err != nil {
			return "", err
		}
	}
	return "", errors.New("could not allocate unique staging path")
}

func safeRemoveStaging(root, staging string) error {
	versions := filepath.Join(root, versionsDirectory)
	clean := filepath.Clean(staging)
	prefix := versions + string(os.PathSeparator) + ".staging-"
	if !strings.HasPrefix(clean, prefix) {
		return errors.New("refusing to remove unexpected staging path")
	}
	info, err := os.Lstat(clean)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("staging path is unsafe")
	}
	return os.RemoveAll(clean)
}

func atomicSymlink(path, target string) error {
	parent := filepath.Dir(path)
	if err := ensureDirectory(parent, 0o700); err != nil {
		return err
	}
	name := filepath.Base(path)
	temporary := filepath.Join(parent, fmt.Sprintf(".%s.tmp-%d", name, os.Getpid()))
	_ = os.Remove(temporary)
	if err := os.Symlink(target, temporary); err != nil {
		return err
	}
	if err := syncDirectory(parent); err != nil {
		_ = os.Remove(temporary)
		return err
	}
	if err := os.Rename(temporary, path); err != nil {
		_ = os.Remove(temporary)
		return err
	}
	return syncDirectory(parent)
}

func syncDirectory(path string) error {
	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open directory for sync: %w", err)
	}
	err = file.Sync()
	closeErr := file.Close()
	if err != nil {
		return fmt.Errorf("sync directory: %w", err)
	}
	if closeErr != nil {
		return fmt.Errorf("close directory: %w", closeErr)
	}
	return nil
}

func syncTree(root string) error {
	err := filepath.Walk(root, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return errors.New("staging payload must not contain symlinks")
		}
		if info.IsDir() {
			return syncDirectory(path)
		}
		file, err := os.OpenFile(path, os.O_RDONLY, 0)
		if err != nil {
			return err
		}
		err = file.Sync()
		closeErr := file.Close()
		if err != nil {
			return err
		}
		return closeErr
	})
	if err != nil {
		return fmt.Errorf("sync upgrade staging: %w", err)
	}
	return nil
}

var _ io.Reader
