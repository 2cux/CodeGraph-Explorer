package com.example.app.package_a;

import com.example.app.package_b.ServiceB;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;

/**
 * Orchestrator depends on ServiceB (from package_b) via import.
 * It also uses ServiceA from the same package.
 * The two "process" methods must NOT create cross-package false edges.
 */
@Service
public class Orchestrator {

    private final ServiceA serviceA;
    private final ServiceB serviceB;

    @Autowired
    public Orchestrator(ServiceA serviceA, ServiceB serviceB) {
        this.serviceA = serviceA;
        this.serviceB = serviceB;
    }

    public void run(String input) {
        // Same-package call - confirmed
        serviceA.process(input);
        // Different package with import - confirmed
        serviceB.process(input);
    }

    // Overloaded methods — must NOT be confirmed
    public void run(String input, String mode) {
        this.run(input + " [" + mode + "]");
    }
}
