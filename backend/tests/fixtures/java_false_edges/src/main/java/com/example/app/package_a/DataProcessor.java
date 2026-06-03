package com.example.app.package_a;

/**
 * Interface with multiple implementations — must NOT confirm
 * edges to any single implementation.
 */
public interface DataProcessor {
    void process(String data);
    String format(String input);
}
