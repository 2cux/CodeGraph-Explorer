package com.example.demo.util;

public class StringUtils {

    public static String capitalize(String input) {
        if (input == null || input.isEmpty()) {
            return input;
        }
        return input.substring(0, 1).toUpperCase() + input.substring(1);
    }

    // Overloaded method
    public static String capitalize(String input, boolean lowerRest) {
        String result = capitalize(input);
        if (lowerRest && result.length() > 1) {
            return result.charAt(0) + result.substring(1).toLowerCase();
        }
        return result;
    }

    public static boolean isEmpty(String input) {
        return input == null || input.trim().isEmpty();
    }
}
