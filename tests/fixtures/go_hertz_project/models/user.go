package models

import (
	"fmt"
	"sync"
)

// User represents a user entity.
type User struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Email string `json:"email"`
}

// UserRepository defines the data access interface.
type UserRepository interface {
	GetAll() []User
	GetByID(id string) *User
	Add(user User) error
	Update(id string, user User) error
	Delete(id string) error
}

// InMemoryUserStore implements UserRepository with in-memory storage.
type InMemoryUserStore struct {
	UserRepository
	mu    sync.RWMutex
	users map[string]User
}

var store = &InMemoryUserStore{
	users: make(map[string]User),
}

var nextID int

func (s *InMemoryUserStore) GetAll() []User {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]User, 0, len(s.users))
	for _, u := range s.users {
		result = append(result, u)
	}
	return result
}

func (s *InMemoryUserStore) GetByID(id string) *User {
	s.mu.RLock()
	defer s.mu.RUnlock()
	u, ok := s.users[id]
	if !ok {
		return nil
	}
	return &u
}

func (s *InMemoryUserStore) Add(user User) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if user.ID == "" {
		nextID++
		user.ID = fmt.Sprintf("user-%d", nextID)
	}
	s.users[user.ID] = user
	return nil
}

func (s *InMemoryUserStore) Update(id string, user User) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.users[id]; !ok {
		return fmt.Errorf("user not found: %s", id)
	}
	user.ID = id
	s.users[id] = user
	return nil
}

func (s *InMemoryUserStore) Delete(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.users, id)
	return nil
}

// Convenience package-level functions.

func GetAllUsers() []User               { return store.GetAll() }
func GetUser(id string) *User           { return store.GetByID(id) }
func AddUser(user User)                 { store.Add(user) }
func UpdateUser(id string, user User)   { store.Update(id, user) }
func DeleteUser(id string)              { store.Delete(id) }

// UserService provides business logic on top of UserRepository.
type UserService struct {
	Repo UserRepository
}

// NewUserService creates a new UserService.
func NewUserService(repo UserRepository) *UserService {
	return &UserService{Repo: repo}
}

// CreateUser validates and creates a user.
func (svc *UserService) CreateUser(user User) error {
	if user.Name == "" {
		return fmt.Errorf("name is required")
	}
	return svc.Repo.Add(user)
}

// Close shuts down the service. Same name as utils.Close for false-edge testing.
func (svc *UserService) Close() {
	fmt.Println("UserService closed")
}
