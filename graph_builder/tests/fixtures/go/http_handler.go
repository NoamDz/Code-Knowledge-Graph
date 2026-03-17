package main

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"

	"github.com/gorilla/mux"
	"github.com/org/repo/internal/auth"
	"github.com/org/repo/internal/service"
)

// Config holds application configuration
type Config struct {
	Port       string
	SocketPath string
	Debug      bool
}

// Server is the main HTTP server
type Server struct {
	config  Config
	router  *mux.Router
	authSvc *auth.Service
}

// NewServer creates a new Server instance
func NewServer(config Config) *Server {
	s := &Server{
		config: config,
		router: mux.NewRouter(),
	}
	s.registerRoutes()
	return s
}

func (s *Server) registerRoutes() {
	s.router.HandleFunc("/api/health", s.handleHealth).Methods("GET")
	s.router.HandleFunc("/api/process", s.handleProcess).Methods("POST")
	s.router.HandleFunc("/api/users/{id}", s.handleGetUser).Methods("GET")

	http.HandleFunc("/metrics", handleMetrics)
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func (s *Server) handleProcess(w http.ResponseWriter, r *http.Request) {
	var req service.ProcessRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	result, err := service.Process(req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	json.NewEncoder(w).Encode(result)
}

func (s *Server) handleGetUser(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	user, err := s.authSvc.GetUser(vars["id"])
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	json.NewEncoder(w).Encode(user)
}

func handleMetrics(w http.ResponseWriter, r *http.Request) {
	fmt.Fprintf(w, "metrics_total 42\n")
}

func main() {
	config := Config{
		Port:       os.Getenv("PORT"),
		SocketPath: "/tmp/go-svc.sock",
	}

	server := NewServer(config)

	// Listen on unix socket for nginx proxy_pass
	listener, err := net.Listen("unix", config.SocketPath)
	if err != nil {
		panic(err)
	}
	defer listener.Close()

	http.Serve(listener, server.router)
}
