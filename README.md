# Roadmap
## 4. Refactor TelegramReportingService to separate concerns
## 5. Crear un sistema de maquina de estados para el servicio de telegram, ejemplos: "Escuchando ordenes, creando tarea, (...)"
## 6. Implementar un "/import" para importar tareas desde un archivo json y un "/export" para exportar tareas a un archivo json
## 7. Pon getId() a ITaskModel de tal modo que una tarea pueda ser seleccionada por su id
## 8. Implementar un /work [work_units] para indicar cuanto tiempo se ha dedicado a una tarea, esto además permite añadir una dependencia mas que sea el IStatisticsService para llevar un registro de las horas trabajadas, del cual se puede calcular un pomodoros per day :o
