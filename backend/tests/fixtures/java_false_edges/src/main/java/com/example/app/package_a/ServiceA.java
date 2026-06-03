package com.example.app.package_a;

/**
 * ServiceA has a "process" method.
 * Package B also has ServiceB with a "process" method.
 * These must NOT be falsely connected.
 */
public class ServiceA {

    public void process(String data) {
        System.out.println("ServiceA processing: " + data);
    }

    public void internalHelper() {
        this.process("internal");
    }
}
