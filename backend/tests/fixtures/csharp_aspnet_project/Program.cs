using CSharpDemo.Services;
using CSharpDemo.Repositories;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

var builder = WebApplication.CreateBuilder(args);

// Service registration
builder.Services.AddScoped<IUserService, UserService>();
builder.Services.AddScoped<IUserRepository, UserRepository>();
builder.Services.AddControllers();

var app = builder.Build();

// Simple minimal API
app.MapGet("/health", () => Results.Ok(new { Status = "Healthy" }));

// Minimal API with handler reference
app.MapGet("/api/info", GetApiInfo);

// MapGroup with prefix
var usersGroup = app.MapGroup("/api/users");
usersGroup.MapGet("/", GetAllUsersMinimal);
usersGroup.MapPost("/", CreateUserMinimal);

// Lambda handler
app.MapGet("/api/status", async (HttpContext context) =>
{
    await context.Response.WriteAsync("OK");
});

app.Run();

// Handler methods for minimal API
static IResult GetApiInfo()
{
    return Results.Ok(new { Name = "CSharpDemo API", Version = "1.0" });
}

static IResult GetAllUsersMinimal()
{
    return Results.Ok(new[] { new { Id = 1, Name = "Test" } });
}

static IResult CreateUserMinimal()
{
    return Results.Created("/api/users/1", new { Id = 1 });
}
