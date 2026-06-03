package com.example.app.package_b;

import com.example.app.package_a.DataProcessor;

public class XmlProcessor implements DataProcessor {

    @Override
    public void process(String data) {
        System.out.println("XML processing: " + data);
    }

    @Override
    public String format(String input) {
        return "<data>" + input + "</data>";
    }
}
