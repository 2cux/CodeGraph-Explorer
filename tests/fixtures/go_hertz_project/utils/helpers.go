package utils

import (
	"fmt"
	"os"
	"time"
)

// WaitFor polls a condition until it returns true or timeout.
func WaitFor(condition func() bool, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if condition() {
			return true
		}
		time.Sleep(100 * time.Millisecond)
	}
	return false
}

// Close is a utility cleanup function. Same name as UserService.Close.
func Close() {
	fmt.Println("utils cleanup done")
}

// NewLogger creates a new Logger.
func NewLogger(prefix string) *Logger {
	return &Logger{prefix: prefix, writer: os.Stdout}
}

// Logger writes structured log messages.
type Logger struct {
	prefix string
	writer *os.File
}

// Log writes a message with the logger's prefix.
func (l *Logger) Log(message string) {
	fmt.Fprintf(l.writer, "[%s] %s\n", l.prefix, message)
}

// Close closes the logger's writer. Same name as Close() and UserService.Close().
func (l *Logger) Close() {
	if l.writer != nil && l.writer != os.Stdout {
		l.writer.Close()
	}
}

// FormatUser formats a user display string.
func FormatUser(name string, age int) string {
	return fmt.Sprintf("%s (%d)", name, age)
}
