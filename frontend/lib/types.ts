export type AssignmentStatus = "planned" | "in_progress" | "done";

export interface ApiAssignment {
  cycle: number;
  runner_name: string;
  course_code: string;
  course_type: string;
  planned_start: string;
  planned_duration_min: number;
  planned_sigma_min: number;
  planned_finish: string;
  actual_start: string | null;
  actual_duration_min: number | null;
  actual_finish: string | null;
  status: AssignmentStatus;
}

export interface ApiNextUp {
  cycle: number;
  runner_name: string;
  course_code: string;
  course_type: string;
  planned_start: string;
  planned_duration_min: number;
}

export interface ApiSchedule {
  assignments: ApiAssignment[];
  next_up: ApiNextUp | null;
  projected_count: number;
  done_count: number;
  in_progress_count: number;
  total_courses: number;
  race_start: string;
  cutoff: string;
  twilight: string;
  last_finish: string | null;
  slack_min: number | null;
  pace_multipliers: Record<string, number>;
  has_plan: boolean;
}
