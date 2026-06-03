package main

import (
	"context"
	"fmt"
	"os"

	"github.com/cloudwego/hertz/pkg/app/server"
	"go-hertz-project/handlers"
	"go-hertz-project/models"
)

// listUsers returns all users as JSON.
func listUsers(c context.Context, ctx *app.RequestContext) {
	users := models.GetAllUsers()
	ctx.JSON(200, users)
}

// healthCheck is a simple health endpoint.
func healthCheck(c context.Context, ctx *app.RequestContext) {
	ctx.JSON(200, map[string]string{"status": "ok"})
}

// authMiddleware returns a Hertz middleware handler.
func authMiddleware() app.HandlerFunc {
	return func(c context.Context, ctx *app.RequestContext) {
		fmt.Println("auth check")
		ctx.Next(c)
	}
}

// adminDashboard shows admin panel.
func adminDashboard(c context.Context, ctx *app.RequestContext) {
	fmt.Println("admin dashboard")
}

func main() {
	h := server.Default()

	// Basic routes
	h.GET("/users", listUsers)
	h.POST("/users", handlers.CreateUser)
	h.PUT("/users/:id", handlers.UpdateUser)
	h.DELETE("/users/:id", handlers.DeleteUser)

	// Route group
	api := h.Group("/api")
	{
		api.GET("/users", listUsers)
		api.GET("/health", healthCheck)
	}

	// Middleware chain
	h.GET("/admin", authMiddleware(), adminDashboard)

	// Inline handler
	h.GET("/ping", func(c context.Context, ctx *app.RequestContext) {
		ctx.JSON(200, map[string]string{"message": "pong"})
	})

	h.Spin()
}
