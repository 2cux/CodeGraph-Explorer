// External assembly calls — should be marked external/unresolved
using Newtonsoft.Json;
using System.Net.Http;
using System.Reflection;

namespace CSharpDemo.EdgeCases;

public class ExternalAssemblyCall
{
    private readonly HttpClient _httpClient;

    public ExternalAssemblyCall(HttpClient httpClient)
    {
        _httpClient = httpClient;
    }

    public async Task<string> CallExternalAsync(string url)
    {
        var response = await _httpClient.GetStringAsync(url);  // external
        var obj = JsonConvert.DeserializeObject(response);     // external
        return obj?.ToString() ?? "";
    }

    public void DynamicCall(object obj)
    {
        // dynamic call — should be marked as dynamic/unresolved
        var method = obj.GetType().GetMethod("SomeMethod");
        method?.Invoke(obj, null);  // reflection
    }

    public async Task ExternalLambdaAsync()
    {
        // lambda calling external
        Func<Task> handler = async () => await _httpClient.GetAsync("https://example.com");
        await handler();
    }
}
