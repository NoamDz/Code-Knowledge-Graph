package server

import (
	"context"
	"fmt"
	"net/http"
)

func main() {
	handler := NewHandler()
	fmt.Println("Starting server")
	http.ListenAndServe(":8080", handler)
}
