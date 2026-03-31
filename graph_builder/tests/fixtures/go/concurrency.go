package worker

import (
	"fmt"
	"time"
)

type Task struct {
	ID   int
	Data string
}

type Worker struct {
	taskQueue    chan *Task
	resultChan   chan string
	done         chan struct{}
}

func NewWorker() *Worker {
	w := &Worker{
		taskQueue:  make(chan *Task, 100),
		resultChan: make(chan string, 50),
		done:       make(chan struct{}),
	}
	return w
}

func (w *Worker) Start() {
	go w.processLoop()
	go func() {
		for result := range w.resultChan {
			fmt.Println(result)
		}
	}()
}

func (w *Worker) processLoop() {
	defer close(w.resultChan)
	defer w.cleanup()

	for task := range w.taskQueue {
		result := w.processTask(task)
		w.resultChan <- result
	}
}

func (w *Worker) processTask(task *Task) string {
	return fmt.Sprintf("processed: %s", task.Data)
}

func (w *Worker) cleanup() {
	fmt.Println("cleaning up")
}

func (w *Worker) Submit(task *Task) {
	w.taskQueue <- task
}

func (w *Worker) Wait() string {
	result := <-w.resultChan
	return result
}

func (w *Worker) WaitWithTimeout() string {
	select {
	case result := <-w.resultChan:
		return result
	case <-time.After(5 * time.Second):
		return "timeout"
	}
}

func (w *Worker) Stop() {
	close(w.taskQueue)
	<-w.done
}
