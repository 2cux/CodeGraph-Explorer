package handlers

import (
	"fmt"
	"net/http"

	"github.com/gin-gonic/gin"
	"go-gin-project/models"
)

// CreateUser handles POST /users
func CreateUser(c *gin.Context) {
	var user models.User
	if err := c.ShouldBindJSON(&user); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	models.AddUser(user)
	c.JSON(http.StatusCreated, user)
}

// UpdateUser handles PUT /users/:id
func UpdateUser(c *gin.Context) {
	id := c.Param("id")
	var user models.User
	if err := c.ShouldBindJSON(&user); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	models.UpdateUser(id, user)
	c.JSON(http.StatusOK, user)
}

// DeleteUser handles DELETE /users/:id
func DeleteUser(c *gin.Context) {
	id := c.Param("id")
	models.DeleteUser(id)
	c.JSON(http.StatusNoContent, nil)
}

// GetUser handles GET /users/:id
func GetUser(c *gin.Context) {
	id := c.Param("id")
	user := models.GetUser(id)
	c.JSON(http.StatusOK, user)
}

// Internal helper — not exported
func validateUser(user models.User) error {
	if user.Name == "" {
		return fmt.Errorf("name is required")
	}
	return nil
}
