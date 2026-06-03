using CSharpDemo.Models;
using Microsoft.Extensions.Logging;

namespace CSharpDemo.Repositories;

public interface IUserRepository
{
    Task<IEnumerable<User>> GetAllAsync();
    Task<User?> GetByIdAsync(int id);
    Task<User> AddAsync(User user);
    Task UpdateAsync(User user);
    Task<bool> DeleteAsync(int id);
}

public class UserRepository : IUserRepository
{
    private readonly List<User> _users = new();
    private readonly ILogger<UserRepository> _logger;
    private static int _nextId = 1;

    public UserRepository(ILogger<UserRepository> logger)
    {
        _logger = logger;
    }

    public Task<IEnumerable<User>> GetAllAsync()
    {
        return Task.FromResult(_users.AsEnumerable());
    }

    public Task<User?> GetByIdAsync(int id)
    {
        var user = _users.FirstOrDefault(u => u.Id == id);
        return Task.FromResult(user);
    }

    public Task<User> AddAsync(User user)
    {
        user.Id = _nextId++;
        user.CreatedAt = DateTime.UtcNow;
        _users.Add(user);
        _logger.LogInformation("User {UserId} added", user.Id);
        return Task.FromResult(user);
    }

    public Task UpdateAsync(User user)
    {
        var existing = _users.FirstOrDefault(u => u.Id == user.Id);
        if (existing != null)
        {
            existing.Name = user.Name;
            existing.Email = user.Email;
        }
        return Task.CompletedTask;
    }

    public Task<bool> DeleteAsync(int id)
    {
        var user = _users.FirstOrDefault(u => u.Id == id);
        if (user != null)
        {
            _users.Remove(user);
            _logger.LogInformation("User {UserId} deleted", id);
            return Task.FromResult(true);
        }
        return Task.FromResult(false);
    }
}
