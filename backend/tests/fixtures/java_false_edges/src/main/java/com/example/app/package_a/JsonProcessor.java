package com.example.app.package_a;

public class JsonProcessor implements DataProcessor {

    @Override
    public void process(String data) {
        System.out.println("JSON processing: " + data);
    }

    @Override
    public String format(String input) {
        return "{\"data\": \"" + input + "\"}";
    }
}
