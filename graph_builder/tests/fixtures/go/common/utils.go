package common

// Utility functions for pp-consumer internal packages.

func FormatKey(prefix, id string) string {
	return prefix + ":" + id
}

func ParseConfig(path string) (map[string]string, error) {
	return nil, nil
}
