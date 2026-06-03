package handlers

import (
	"context"
	"fmt"
	"net/http"

	"github.com/cloudwego/hertz/pkg/app"
	"go-hertz-project/models"
)

// CreateUser handles POST /users.
func CreateUser(c context.Context, ctx *app.RequestContext) {
	var user models.User
	if err := ctx.Bind(&user); err != nil {
		ctx.JSON(400, map[string]string{"error": "invalid request"})
		return
	}
	if err := validateUser(&user); err != nil {
		ctx.JSON(400, map[string]string{"error": err.Error()})
		return
	}
	models.AddUser(user)
	ctx.JSON(201, user)
}

// UpdateUser handles PUT /users/:id.
func UpdateUser(c context.Context, ctx *app.RequestContext) {
	id := ctx.Param("id")
	var user models.User
	if err := ctx.Bind(&user); err != nil {
		ctx.JSON(400, map[string]string{"error": "invalid request"})
		return
	}
	models.UpdateUser(id, user)
	ctx.JSON(200, user)
}

// DeleteUser handles DELETE /users/:id.
func DeleteUser(c context.Context, ctx *app.RequestContext) {
	id := ctx.Param("id")
	models.DeleteUser(id)
	ctx.JSON(204, nil)
}

// GetUser handles GET /users/:id.
func GetUser(c context.Context, ctx *app.RequestContext) {
	id := ctx.Param("id")
	user := models.GetUser(id)
	if user == nil {
		ctx.JSON(404, map[string]string{"error": "not found"})
		return
	}
	ctx.JSON(200, user)
}

// validateUser is an unexported helper.
func validateUser(user *models.User) error {
	if user.Name == "" {
		return fmt.Errorf("name is required")
	}
	return nil
}
