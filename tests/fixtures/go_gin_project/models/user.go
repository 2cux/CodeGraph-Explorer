package models

import (
	"fmt"
	"sync"
)

// User represents a user in the system
type User struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Email string `json:"email"`
}

// UserRepository interface for user storage
type UserRepository interface {
	GetAll() []User
	GetByID(id string) User
	Add(user User)
	Update(id string, user User)
	Delete(id string)
}

// InMemoryUserStore implements UserRepository
type InMemoryUserStore struct {
	UserRepository
	users map[string]User
	mu    sync.RWMutex
}

var store = &InMemoryUserStore{
	users: make(map[string]User),
}

// Store-level methods (receiver on struct)
func (s *InMemoryUserStore) GetAll() []User {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]User, 0, len(s.users))
	for _, u := range s.users {
		result = append(result, u)
	}
	return result
}

func (s *InMemoryUserStore) GetByID(id string) User {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.users[id]
}

func (s *InMemoryUserStore) Add(user User) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if user.ID == "" {
		user.ID = fmt.Sprintf("user-%d", len(s.users)+1)
	}
	s.users[user.ID] = user
}

func (s *InMemoryUserStore) Update(id string, user User) {
	s.mu.Lock()
	defer s.mu.Unlock()
	user.ID = id
	s.users[id] = user
}

func (s *InMemoryUserStore) Delete(id string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.users, id)
}

// Package-level convenience functions
func GetAllUsers() []User {
	return store.GetAll()
}

func GetUser(id string) User {
	return store.GetByID(id)
}

func AddUser(user User) {
	store.Add(user)
}

func UpdateUser(id string, user User) {
	store.Update(id, user)
}

func DeleteUser(id string) {
	store.Delete(id)
}

// Service struct — constructor pattern
type UserService struct {
	repo UserRepository
}

// NewUserService creates a new UserService
func NewUserService(repo UserRepository) *UserService {
	return &UserService{repo: repo}
}

func (svc *UserService) CreateUser(user User) error {
	if user.Name == "" {
		return fmt.Errorf("name is required")
	}
	svc.repo.Add(user)
	return nil
}

// Close waits for pending operations (same name as different function in another pkg)
func (svc *UserService) Close() {
	fmt.Println("UserService closed")
}
