package labnet

import (
	"crypto/rand"
	"encoding/base32"
	"encoding/hex"
	"io"
	"net/url"
	"strconv"
	"strings"

	"golang.org/x/crypto/sha3"
)

// ValidatePrivateRPC checks an explicitly selected private route, not the Tor
// daemon or service's authenticity. Independent chain/config pins still apply.
// Unlike the legacy endpoint validator, a canonical onion target may use any
// nonzero port; the local proxy retains the original 1024..65535 port policy.
func ValidatePrivateRPC(endpoint, proxy string) error {
	if len(proxy) > len("127.0.0.1:65535") || ValidateEndpoint("http://"+proxy) != nil {
		return ErrEndpoint
	}
	_, _, err := parseOnionEndpoint(endpoint)
	return err
}

func parseOnionEndpoint(endpoint string) (string, uint16, error) {
	if len(endpoint) > 75 {
		return "", 0, ErrEndpoint
	}
	u, err := url.Parse(endpoint)
	if err != nil || u.Scheme != "http" || u.User != nil || u.Opaque != "" {
		return "", 0, ErrEndpoint
	}
	host := u.Hostname()
	port, err := strconv.ParseUint(u.Port(), 10, 16)
	if err != nil || port == 0 || strconv.FormatUint(port, 10) != u.Port() ||
		len(host) != 62 || !strings.HasSuffix(host, ".onion") ||
		u.Host != host+":"+u.Port() || endpoint != "http://"+host+":"+u.Port() {
		return "", 0, ErrEndpoint
	}
	for _, c := range host[:56] {
		if !(c >= 'a' && c <= 'z' || c >= '2' && c <= '7') {
			return "", 0, ErrEndpoint
		}
	}
	decoded, err := base32.StdEncoding.WithPadding(base32.NoPadding).DecodeString(strings.ToUpper(host[:56]))
	if err != nil || len(decoded) != 35 || decoded[34] != 3 {
		return "", 0, ErrEndpoint
	}
	transcript := append([]byte(".onion checksum"), decoded[:32]...)
	transcript = append(transcript, decoded[34])
	checksum := sha3.Sum256(transcript)
	if decoded[32] != checksum[0] || decoded[33] != checksum[1] {
		return "", 0, ErrEndpoint
	}
	// The checksum identifies a syntactically canonical address; validating
	// its Ed25519 service key and onion handshake belongs to trusted Tor.
	return host, uint16(port), nil
}

func newPrivatePeer(endpoint, proxy string) (*peer, error) {
	if err := ValidatePrivateRPC(endpoint, proxy); err != nil {
		return nil, err
	}
	host, port, _ := parseOnionEndpoint(endpoint)
	var entropy [32]byte
	if _, err := io.ReadFull(rand.Reader, entropy[:]); err != nil {
		return nil, errPrivateSOCKS
	}
	dialer := &onionDialer{proxy: proxy, host: host, port: port, isolation: hex.EncodeToString(entropy[:])}
	return newRPCPeer(endpoint, dialer.dialContext)
}

// The choice is explicit and exclusive. A malformed/failed private route must
// never enter the legacy loopback path or try an environment-selected proxy.
func newPeerForOptions(o SyncOptions) (*peer, error) {
	if o.SOCKSProxy != "" {
		return newPrivatePeer(o.Endpoint, o.SOCKSProxy)
	}
	return newPeer(o.Endpoint)
}
