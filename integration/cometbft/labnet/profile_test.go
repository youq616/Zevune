package labnet

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
	"github.com/youq616/Zevune/integration/cometbft/poolapp"
	"github.com/youq616/Zevune/internal/poolbridge"
)

// Framing-only public fixture. It has no valid Orchard note openings and is
// never passed to a worker or used as payment/issuance authorization.
func profileManifest(magic string) []byte {
	header := 82
	if magic == "ZVTGEN01" {
		header = 50
	}
	raw := make([]byte, header+115)
	copy(raw, magic)
	network := sha256.Sum256([]byte(poolbridge.Network))
	copy(raw[8:40], network[:])
	binary.BigEndian.PutUint64(raw[40:48], 100_000)
	binary.BigEndian.PutUint16(raw[48:50], 1)
	if header == 82 {
		raw[50] = 1
	}
	binary.BigEndian.PutUint64(raw[header+43:header+51], 100_000)
	return raw
}

func profileConfiguration(t *testing.T, magic string, configuration uint32, app uint64) (string, Hash) {
	t.Helper()
	n, _ := signingNetwork(t)
	n.genesis.ConsensusParams.Version.App = app
	home := t.TempDir()
	asset := profileManifest(magic)
	assetPin := sha256.Sum256(asset)
	n.genesis.AppState, _ = json.Marshal(struct {
		Digest string `json:"test_genesis_sha256"`
	}{HashText(assetPin)})
	genesis, err := cmtjson.MarshalIndent(n.genesis, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	config := publicConfig{
		Version: configuration, ChainID: poolapp.ChainID,
		AssetDigest: HashText(assetPin), ConsensusDigest: HashText(sha256.Sum256(genesis)),
		NodeIDs: []string{strings.Repeat("0", 40), strings.Repeat("1", 40), strings.Repeat("2", 40), strings.Repeat("3", 40)},
	}
	raw, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	for name, contents := range map[string][]byte{assetName: asset, genesisName: genesis, configName: raw} {
		if err := writeNew(filepath.Join(home, name), contents); err != nil {
			t.Fatal(err)
		}
	}
	return filepath.Join(home, configName), sha256.Sum256(raw)
}

func TestPinnedNetworkProfileCannotChangeConfigurationOrAppVersion(t *testing.T) {
	for _, magic := range []string{"ZVTGEN01", "ZVTGEN02", "ZVTGEN03"} {
		for _, configuration := range []uint32{1, 2} {
			for _, app := range []uint64{poolapp.AppVersion, poolapp.ActiveAppVersion} {
				t.Run(magic+"/"+strconv.Itoa(int(configuration))+"/"+strconv.Itoa(int(app)), func(t *testing.T) {
					path, pin := profileConfiguration(t, magic, configuration, app)
					n, err := Load(path, pin)
					active := magic == "ZVTGEN03"
					want := (active && configuration == 2 && app == poolapp.ActiveAppVersion) ||
						(!active && configuration == 1 && app == poolapp.AppVersion)
					if (err == nil) != want {
						t.Fatalf("profile/version binding: accepted=%v expected=%v error=%v", err == nil, want, err)
					}
					if want && (n.Profile() == poolbridge.ActiveSegmentsV1) != active {
						t.Fatal("authenticated profile mismatch")
					}
				})
			}
		}
	}
}

func TestSignedHeadersUseAuthenticatedProfileHeightAndVersion(t *testing.T) {
	for _, profile := range []poolbridge.StorageProfile{poolbridge.LegacyJournal, poolbridge.ActiveSegmentsV1} {
		n, keys := signingNetwork(t)
		n.profile = profile
		n.genesis.ConsensusParams.Version.App = poolapp.AppVersionForProfile(profile)
		part := types.PartSetHeader{Total: 1, Hash: bytes.Repeat([]byte{3}, 32)}
		for _, height := range []uint64{1, 10000, 10001, profile.MaxHeight(), profile.MaxHeight() + 1} {
			h := headerTemplate(n, int64(height))
			err := n.validateHeader(signHeader(t, n, keys, h, part, 4), int64(height), time.Now())
			if (err == nil) != (height <= profile.MaxHeight()) {
				t.Fatalf("profile=%v height=%d error=%v", profile, height, err)
			}
		}
		wrong := headerTemplate(n, 1)
		wrong.Version.App = poolapp.AppVersionForProfile(profile) ^ 1 // swap 2 and 3
		if n.validateHeader(signHeader(t, n, keys, wrong, part, 4), 1, time.Now()) == nil {
			t.Fatal("quorum signatures bypassed the authenticated application version")
		}
	}
}

func TestActiveCheckpointUsesPinnedNetworkAndRetainsLegacyBounds(t *testing.T) {
	path, pin := profileConfiguration(t, "ZVTGEN03", 2, poolapp.ActiveAppVersion)
	n, err := Load(path, pin)
	if err != nil {
		t.Fatal(err)
	}
	hash := HashText(Hash{1})
	for _, height := range []string{"0", "10000", "10001", "1000000"} {
		c, err := n.ParseStorageCheckpoint(height, hash)
		if err != nil || n.ValidateStorageCheckpoint(c) != nil || strconv.FormatUint(c.Height, 10) != height {
			t.Fatal("active checkpoint rejected", height, err)
		}
		if err := n.validateReferenceCheckpoint(SyncOptions{}, &c); err != nil {
			t.Fatal("active reference checkpoint rejected", err)
		}
	}
	for _, height := range []string{"1000001", "010001", "-1", "+1", "1.0", ""} {
		if _, err := n.ParseStorageCheckpoint(height, hash); err == nil {
			t.Fatal("invalid active checkpoint accepted")
		}
	}
	if _, err := ParseStorageCheckpoint("10001", hash); err == nil {
		t.Fatal("package-level legacy checkpoint bounds changed")
	}
	if err := (&Network{}).ValidateStorageCheckpoint(StorageCheckpoint{Height: 10001, AppHash: Hash{1}}); err == nil {
		t.Fatal("legacy network accepted an active-height checkpoint")
	}
}

func TestActiveCapacityReportsLogicalBytesAndExactCheckpoint(t *testing.T) {
	snapshot := poolbridge.ActiveStorage{
		Summary: poolbridge.Summary{Height: 10001, AppHash: Hash{1}, Commitments: 2},
		LogicalBytes: 108 + 10001*150, Segments: 2, TailBytes: 3011 * 150,
	}
	c := StorageCheckpoint{Height: snapshot.Summary.Height, AppHash: snapshot.Summary.AppHash}
	r, err := activeStorageReport(snapshot, &c)
	if err != nil || r.JournalBytes != snapshot.LogicalBytes || r.JournalLimitBytes != poolbridge.ActiveSegmentsV1.MaxJournalBytes() ||
		r.RecordsRemaining+r.Height != poolbridge.ActiveSegmentsV1.MaxHeight() || r.Segments != 2 || r.TailBytes != snapshot.TailBytes ||
		r.StorageProfile != "active_segments_v1" || !r.ExpectedCheckpointMatched || !r.EmptyBlockFitsLimits ||
		r.ConsensusVerified || r.NetworkAccessed || r.RealFundsAllowed {
		t.Fatal("active capacity mismatch or overclaim", r, err)
	}
	wrong := c
	wrong.Height--
	if r, err := activeStorageReport(snapshot, &wrong); !errors.Is(err, ErrStorageCheckpoint) || r.Scope != "" {
		t.Fatal("complete historical prefix accepted as exact tip")
	}
	for _, change := range []func(*poolbridge.ActiveStorage){
		func(s *poolbridge.ActiveStorage) { s.Summary.Height = 1000001 },
		func(s *poolbridge.ActiveStorage) { s.LogicalBytes = poolbridge.ActiveSegmentsV1.MaxJournalBytes() + 1 },
		func(s *poolbridge.ActiveStorage) { s.Segments = poolbridge.ActiveMaxSegments + 1 },
		func(s *poolbridge.ActiveStorage) { s.Segments = 0 },
		func(s *poolbridge.ActiveStorage) { s.TailBytes = 0 },
		func(s *poolbridge.ActiveStorage) { s.TailBytes = poolbridge.ActiveSegmentBytes + 1 },
	} {
		bad := snapshot
		change(&bad)
		if r, err := activeStorageReport(bad, nil); err == nil || r.Scope != "" {
			t.Fatal("inconsistent active capacity accepted")
		}
	}
}

func TestActiveStorageCopyRefusesBeforeReadingOrCreatingAnyPath(t *testing.T) {
	n := &Network{profile: poolbridge.ActiveSegmentsV1}
	root := t.TempDir()
	output := filepath.Join(root, "must-not-exist")
	_, err := n.CopyStorageAtCheckpoint(context.Background(), StorageCopyOptions{
		Source: filepath.Join(root, "source"), Destination: output,
		Expected: StorageCheckpoint{AppHash: Hash{1}},
	})
	if !errors.Is(err, ErrStorageProfile) {
		t.Fatal("active storage-copy did not explicitly refuse its unsupported format", err)
	}
	if _, err := os.Stat(output); !os.IsNotExist(err) {
		t.Fatal("unsupported copy created a destination")
	}
}
