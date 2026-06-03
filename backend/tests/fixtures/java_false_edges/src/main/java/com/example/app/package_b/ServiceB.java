package com.example.app.package_b;

/**
 * ServiceB also has a "process" method — same name as ServiceA.process.
 * This must NOT create a false edge between ServiceA and ServiceB.
 */
public class ServiceB {

    public void process(String data) {
        System.out.println("ServiceB processing: " + data);
    }
}
