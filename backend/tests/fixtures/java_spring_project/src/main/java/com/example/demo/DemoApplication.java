package com.example.demo;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import com.example.demo.util.StringUtils;

@SpringBootApplication
public class DemoApplication {

    public static void main(String[] args) {
        // Static method call from utility class
        String appName = StringUtils.capitalize("demo application");
        System.out.println("Starting " + appName + "...");
        SpringApplication.run(DemoApplication.class, args);
    }
}
