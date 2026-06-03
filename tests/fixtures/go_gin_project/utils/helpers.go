package utils

import (
	"fmt"
	"os"
	"time"
)

// WaitFor polls a condition function until it returns true or timeout
func WaitFor(condition func() bool, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if condition() {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	return fmt.Errorf("timeout after %v", timeout)
}

// Close cleans up resources (same function name as models.UserService.Close)
func Close() {
	fmt.Println("utils: closing resources")
}

// NewLogger creates a new logger instance
func NewLogger(prefix string) *Logger {
	return &Logger{prefix: prefix}
}

// Logger struct with alias import example
type Logger struct {
	prefix string
	writer *os.File
}

func (l *Logger) Log(message string) {
	fmt.Fprintf(l.writer, "[%s] %s", l.prefix, message)
}

// Close on Logger — demonstrates same method name on different receiver
func (l *Logger) Close() {
	if l.writer != nil {
		l.writer.Close()
	}
}

// External package call example
func FormatUser(name string, age int) string {
	return fmt.Sprintf("User: %s (Age: %d)", name, age)
}
