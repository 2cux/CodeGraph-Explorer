package main

import (
	"fmt"
	"os"

	"github.com/gin-gonic/gin"
	"go-gin-project/handlers"
	"go-gin-project/models"
)

func main() {
	r := gin.Default()

	// Basic routes
	r.GET("/users", listUsers)
	r.POST("/users", handlers.CreateUser)
	r.PUT("/users/:id", handlers.UpdateUser)
	r.DELETE("/users/:id", handlers.DeleteUser)

	// Route group
	api := r.Group("/api")
	{
		api.GET("/users", listUsers)
		api.GET("/health", healthCheck)
	}

	// Route with middleware
	r.GET("/admin", authMiddleware(), adminDashboard)

	// Inline handler
	r.GET("/ping", func(c *gin.Context) {
		c.JSON(200, gin.H{"message": "pong"})
	})

	r.Run(":8080")
}

func listUsers(c *gin.Context) {
	users := models.GetAllUsers()
	c.JSON(200, users)
}

func healthCheck(c *gin.Context) {
	c.JSON(200, gin.H{"status": "ok"})
}

func authMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		fmt.Println("auth check")
		c.Next()
	}
}

func adminDashboard(c *gin.Context) {
	fmt.Println("admin dashboard")
}
