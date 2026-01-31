# Enhanced /schedule Command Documentation

## Overview

The `/schedule` command has been enhanced to support hours-per-day specification and automatic task splitting when effort requirements would result in unrealistic deadlines.

## New Features

### 1. Time Format Support

The `/schedule` command now accepts various time formats for specifying daily effort:

- **Hours**: `2h`, `3.5h`, `1.5h`
- **Minutes**: `90m`, `120m`, `30m`  
- **Pomodoros**: `4p`, `6.5p`, `2p`
- **Numeric**: `2`, `1.5` (interpreted as pomodoros for backward compatibility)

### 2. Automatic Task Splitting

When the specified daily effort would result in a severity value below 1 (indicating unrealistic scheduling), the system automatically splits the task into smaller, manageable parts.

#### Split Logic

- **Trigger**: When `severity = 1 / effort_per_day < 1`
- **Split Count**: `ceil(1 / severity)` to ensure each split has `severity >= 1`
- **Effort Distribution**: Total effort divided equally among split tasks
- **Naming**: Sequential naming pattern: `"Original Task 1/N"`, `"Original Task 2/N"`, etc.

### 3. Enhanced User Feedback

- **Normal Scheduling**: Shows updated task information
- **Task Splitting**: Displays clear message indicating the task was split due to high effort per day requirements
- **Split Count**: Informs user how many parts the task was divided into

## Usage Examples

### Basic Time Specification
```
/schedule 2h          # Schedule with 2 hours per day
/schedule 90m         # Schedule with 90 minutes per day  
/schedule 4p          # Schedule with 4 pomodoros per day
/schedule 1.5         # Schedule with 1.5 pomodoros per day (backward compatible)
```

### Auto-calculation (Unchanged)
```
/schedule             # Auto-calculate based on remaining time
/schedule auto        # Explicitly request auto-calculation
```

### Task Splitting Scenarios

#### Example 1: Large Task with High Daily Effort
```
Original Task: "Develop new feature" (Total: 20 pomodoros)
Command: /schedule 15h (60 pomodoros per day)
Result: Task split into 2 parts:
- "Develop new feature 1/2" (10 pomodoros)
- "Develop new feature 2/2" (10 pomodoros)
```

#### Example 2: Moderate Task with Reasonable Effort
```
Original Task: "Write documentation" (Total: 8 pomodoros)  
Command: /schedule 2h (4.8 pomodoros per day)
Result: No splitting - single task with adjusted schedule
```

## Technical Implementation

### Algorithm Flow

1. **Parse Input**: Convert time specification to pomodoros per day
2. **Calculate Severity**: `severity = 1 / effort_per_day`
3. **Check Split Threshold**: If `severity < 1`, proceed with splitting
4. **Create Split Tasks**: 
   - Calculate split count: `ceil(1 / severity)`
   - Distribute effort equally: `total_effort / split_count`
   - Generate sequential naming
   - Apply optimal scheduling (severity = 1) to each split
5. **Save and Report**: Save all tasks and provide user feedback

### Severity Explanation

- **Severity >= 1**: Realistic scheduling, task remains as single unit
- **Severity < 1**: Unrealistic scheduling indicating too much daily effort requested
- **Target Severity**: After splitting, each part targets severity = 1 (optimal balance)

### Time Conversion

All time formats are internally converted to pomodoros:
- **1 hour = 2.4 pomodoros** (assuming 25-minute pomodoros)
- **1 minute = 1/25 pomodoros**
- **Direct pomodoro values** are used as-is

## Error Handling

### Invalid Time Formats
- Unrecognized formats fall back to auto-calculation
- No error messages for invalid formats (graceful degradation)

### Edge Cases
- **Zero effort**: Raises `ZeroDivisionError` (requires positive effort)
- **Negative effort**: Handled by TimeAmount validation
- **Very large tasks**: May result in many splits (mathematically sound)

## Backward Compatibility

- **Numeric parameters**: Continue to work as pomodoros per day
- **Empty parameters**: Still trigger auto-calculation
- **Existing behavior**: Normal scheduling (no splitting) remains unchanged when severity >= 1

## User Experience Improvements

### Clear Messaging
- Split notifications explain why splitting occurred
- Count information helps users understand the division
- First split task is automatically selected for immediate review

### Task Management
- Split tasks appear as independent entities in task lists
- Each split can be managed (completed, rescheduled, etc.) independently
- Original task is transformed, not deleted

## Future Considerations

### Potential Enhancements
- **Batch Operations**: Optional task provider method for improved performance
- **Split Strategies**: Alternative splitting algorithms (time-based, dependency-aware)
- **User Preferences**: Configurable split thresholds and naming patterns
- **Smart Dependencies**: Automatic dependency creation between split parts

### Performance Notes
- **Task Creation**: Uses existing `createDefaultTask()` method
- **Property Copying**: Manually copies all relevant task properties
- **Transactional Safety**: Each task saved individually (atomic operations)

## Testing Coverage

### Unit Tests
- Time format parsing (hours, minutes, pomodoros)
- Splitting logic and calculations
- Property copying accuracy
- Boundary conditions (severity exactly 1)
- Error handling scenarios

### Integration Tests  
- Full command workflow with splitting
- Task provider interactions
- User interface feedback
- Multiple task creation and saving

This enhanced `/schedule` command provides a more intuitive and robust scheduling experience while maintaining full backward compatibility with existing usage patterns.