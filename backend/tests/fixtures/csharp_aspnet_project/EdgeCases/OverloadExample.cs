// Overloaded methods in the same class — should NOT be confirmed directly
namespace CSharpDemo.EdgeCases;

public class OverloadExample
{
    public void Process(string input) { }
    public void Process(int input) { }
    public void Process(string input, int count) { }

    public void Caller()
    {
        Process("hello");    // overloaded — should not be directly confirmed
        Process(42);         // overloaded — should not be directly confirmed
    }
}
