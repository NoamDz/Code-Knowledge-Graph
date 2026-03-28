package service

type Task interface {
	Process() error
	Close() error
}

type TasksReader interface {
	ReadTasks() ([]Task, error)
}

type EmptyConfig interface{}

type ModelPredictionTask struct {
	modelName string
}

func (m *ModelPredictionTask) Process() error {
	return nil
}

func (m *ModelPredictionTask) Close() error {
	return nil
}

func (m *ModelPredictionTask) Init() error {
	return nil
}

type GeneralTasksReader struct {
	configPath string
}

func (g *GeneralTasksReader) ReadTasks() ([]Task, error) {
	return nil, nil
}

func (g *GeneralTasksReader) Validate() error {
	return nil
}
