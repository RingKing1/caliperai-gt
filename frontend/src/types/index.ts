
import type { NullToUndefined, Schema } from './generated';

export * from './auth';

export * from './chat';


export type TaskStatus = Schema<'TaskStatus'>;

export type TaskStage =
  | 'annotation'
  | 'qa'
  | 'customer_qa'
  | 'accepted';

export type AnnotationType =
  | 'cuboid'
  | 'box2d'
  | 'fusion_box2d'
  | 'polyline'
  | 'polygon'
  | 'keypoints'
  | 'segmentation_3d'
  | 'segmentation_2d';

export type AnnotationSource =
  | 'manual'
  | 'auto'
  | 'auto_manual'
  | 'auto_interpolated'
  | 'airflow_model_v1'
  | 'airflow_model_v2'
  | 'imported'
  | 'qa_correction';


export interface Point2D {
  x: number;
  y: number;
}

export interface Point3D {
  x: number;
  y: number;
  z: number;
}

export type BBox2D = Schema<'BBox2D'>;

export interface Dimensions3D {
  length: number;
  width: number;
  height: number;
}

export interface Rotation3D {
  yaw: number;
  pitch: number;
  roll: number;
}


export type ExtrinsicCalibration = Schema<'ExtrinsicCalibration'>;

// Backend IntrinsicCalibration now carries resolution/camera_model (the old
// frontend-only drift is closed); nullables follow the undefined convention.
export type IntrinsicCalibration = NullToUndefined<Schema<'IntrinsicCalibration'>>;

export type CameraModel = NonNullable<IntrinsicCalibration['camera_model']>;

export interface CameraCalibration {
  extrinsic: ExtrinsicCalibration;
  intrinsic: IntrinsicCalibration;
}

export interface SceneCalibration {
  lidar_to_cameras: Record<string, CameraCalibration>;
  ego_to_lidar?: ExtrinsicCalibration;
}


export interface CuboidData {
  center: Point3D;
  dimensions: Dimensions3D;
  rotation: Rotation3D;
  confidence?: number;
}

export interface Box2DData {
  camera_id: string;
  bbox: BBox2D;
}

export interface FusionBox2DData {
  camera_id: string;
  bbox: BBox2D;
  parent_annotation_id: string;
  is_manually_adjusted: boolean;
}

export interface PolylineData {
  camera_id: string;
  points: number[][];
  is_closed: boolean;
  bezier: boolean;
}

export interface PolygonData {
  camera_id: string;
  points: number[][];
}

export interface Keypoint {
  x: number;
  y: number;
  visibility: 0 | 1 | 2;
}

export interface KeypointsData {
  camera_id: string;
  skeleton_id: string;
  keypoints: Record<string, Keypoint>;
}

export interface Segmentation3DData {
  blob_url?: string;
  compression: string;
  point_count: number;
  class_mapping: Record<string, string>;
}

export interface Segmentation2DData {
  camera_id: string;
  mask_url?: string;
  polygons?: number[][][];
}

export type AnnotationData =
  | CuboidData
  | Box2DData
  | FusionBox2DData
  | PolylineData
  | PolygonData
  | KeypointsData
  | Segmentation3DData
  | Segmentation2DData;


export interface AttributeDefinition {
  type: 'boolean' | 'string' | 'number' | 'enum';
  default?: unknown;
  options?: string[];
  required?: boolean;
  description?: string;
  mutable?: boolean;
}

// Backend always serializes applies_to (default_factory=list); nullables
// (options/description/default) follow the frontend's undefined convention.
export type SharedAttributeDefinition = NullToUndefined<
  Omit<Schema<'SharedAttributeDefinition'>, 'applies_to'>
> & {
  applies_to: string[];
};

export interface KeypointDefinition {
  id: string;
  name: string;
  color?: string;
}

export interface SkeletonDefinition {
  keypoints: KeypointDefinition[];
  bones: [string, string][];
}

export interface ClassDefinition {
  id: string;
  name: string;
  color: string;
  type: AnnotationType[];
  attributes: Record<string, AttributeDefinition>;
  skeleton?: string;
  description?: string;
  default_dimensions?: [number, number, number];
  single_click_placement?: boolean;
  instance_prefix?: string;
}

export interface TaxonomyConfig {
  classes: ClassDefinition[];
  skeletons: Record<string, SkeletonDefinition>;
  annotation_rules: {
    min_points_polyline: number;
    min_points_polygon: number;
    allow_overlapping_boxes: boolean;
    require_track_id: boolean;
  };
  shared_attributes?: SharedAttributeDefinition[];
}

export type TaxonomyAnnotationMode = Schema<'TaxonomyAnnotationMode'>;

export interface Taxonomy {
  id: string;
  organization_id?: string;
  name: string;
  description?: string;
  version: string;
  annotation_mode: TaxonomyAnnotationMode;
  classes: ClassDefinition[];
  skeletons: Record<string, SkeletonDefinition>;
  annotation_rules: {
    min_points_polyline: number;
    min_points_polygon: number;
    allow_overlapping_boxes: boolean;
    require_track_id: boolean;
  };
  shared_attributes?: SharedAttributeDefinition[];
  created_at: string;
  updated_at: string;
}

export interface DatasetTaxonomiesByMode {
  fusion_3d: Taxonomy | null;
  '2d_only': Taxonomy | null;
}


// stats carries default_factory=CampaignStats on the response model, so it is
// present on every payload even though OpenAPI marks it optional.
export type Campaign = Omit<NullToUndefined<Schema<'CampaignResponse'>>, 'stats'> & {
  stats: Schema<'CampaignStats'>;
};

export type CampaignCreateRequest = Schema<'CampaignCreate'>;

export type CampaignUpdateRequest = Schema<'CampaignUpdate'>;

export type Dataset = NullToUndefined<Schema<'DatasetResponse'>>;

// Backend marks these optional in the schema, but it always sends all six.
export type DatasetStats = Required<Schema<'DatasetStats'>>;

export interface DatasetDetailResponse extends Dataset {
  taxonomies: Taxonomy[];
  scenes: Scene[];
  stats: DatasetStats;
}

export interface Scene {
  id: string;
  dataset_id: string;
  name: string;
  description?: string;
  metadata: Record<string, unknown>;
  frame_count: number;
  fps: number;
  calibration: SceneCalibration;
  storage_paths: {
    lidar_base: string;
    cameras: Record<string, string>;
    ego_poses?: string;
  };
  tasks?: Task[];
  deadline?: string;
  selected_taxonomy_id?: string;
  created_at: string;
  updated_at: string;
}

export interface ImportJobResult {
  success: boolean;
  message: string;
  scenes_imported: number;
  frames_imported: number;
  errors: string[];
  renamed_scenes: Array<{
    original_name: string;
    new_name: string;
    scene_id: string;
  }>;
}

// Backend types job_type/status as free strings and result as a generic dict;
// keep the frontend's narrowed literals and structured ImportJobResult.
export type ImportJob = Omit<
  NullToUndefined<Schema<'ImportJobResponse'>>,
  'job_type' | 'status' | 'result'
> & {
  job_type: 'zip' | 'upload';
  status: 'pending' | 'running' | 'completed' | 'failed';
  result?: ImportJobResult | null;
};

// file_paths.cameras is required in practice (every frame carries the camera
// map, possibly empty); keep the historical frontend contract.
export type Frame = Omit<NullToUndefined<Schema<'FrameResponse'>>, 'file_paths'> & {
  file_paths: Omit<Schema<'FrameFilePaths'>, 'cameras'> & {
    cameras: Record<string, string>;
  };
  // UI-only markers used by context-frame rendering.
  is_context?: boolean;
  is_readonly?: boolean;
};

export interface TaskTaxonomyStatus {
  taxonomy_id: string;
  taxonomy_name: string;
  annotation_mode?: string;
  stage: TaskStage;
  status: TaskStatus;
  revision_count: number;
  started_at?: string;
  submitted_at?: string;
  assignee_id?: string;
  reviewer_id?: string;
  customer_reviewer_id?: string;
}

// TaskConfig arrays are always present in task payloads consumed by the editor.
export interface TaskConfig {
  required_annotation_types: AnnotationType[];
  required_classes: string[];
  auto_annotation_enabled: boolean;
  quality_checks: string[];
}

export type Task = Omit<
  NullToUndefined<Schema<'TaskResponse'>>,
  'stage' | 'config'
> & {
  stage: TaskStage;
  config: TaskConfig;
};

export type User = NullToUndefined<Schema<'UserResponse'>>;

export interface Annotation {
  id: string;
  task_id: string;
  frame_id: string;
  track_id?: string;
  camera_id?: string;
  type: AnnotationType;
  class_id: string;
  data: AnnotationData;
  attributes: Record<string, unknown>;
  source: AnnotationSource;
  taxonomy_id?: string;
  is_verified: boolean;
  verified_by?: string;
  verified_at?: string;
  created_at: string;
  updated_at: string;
  is_keyframe?: boolean;
  is_static?: boolean;
}


export interface Track {
  id: string;
  class_id: string;
  attributes: Record<string, unknown>;
  frame_annotations: Map<string, string>;
  keyframe_ids: Set<string>;
  created_at: string;
  updated_at: string;

  start_frame_index: number | null;
  end_frame_index: number | null;
  is_static: boolean;
}

export interface TrackKeyframe {
  frame_id: string;
  frame_index: number;
  annotation_id: string;
  data: CuboidData;
}

export interface InterpolatedFrame {
  frame_id: string;
  frame_index: number;
  data: CuboidData;
  is_keyframe: boolean;
}


export interface EditorTool {
  id: string;
  name: string;
  icon: string;
  type: 'select' | 'cuboid' | 'box2d' | 'polyline' | 'polygon' | 'keypoints' | 'brush3d' | 'lasso3d' | 'track' | 'flag_missing';
  shortcut?: string;
}

export interface ViewState {
  zoom: number;
  pan: Point2D;
  rotation?: number;
}

export type CoordinateFrame = 'world' | 'ego' | 'lidar';

export interface CameraViewState {
  isActive: boolean;
  cameraId: string | null;
  showImagePlane: boolean;
  frustumOnlyMode: boolean;
  imageOnlyMode: boolean;
}

export interface GroundPlaneSettings {
  enabled: boolean;
  distanceThreshold: number;
  samplePercent: number;
}

export interface DetectedGroundPlane {
  a: number;
  b: number;
  c: number;
  d: number;
}

export interface ClipBoxSettings {
  enabled: boolean;
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
  zMin: number;
  zMax: number;
}

export interface LidarViewState {
  camera: {
    position: Point3D;
    target: Point3D;
    up: Point3D;
  };
  pointSize: number;
  colorMode: 'intensity' | 'height' | 'height_above_ground' | 'class';
  centerOnEgo: boolean;
  coordinateFrame: CoordinateFrame;
  cameraView: CameraViewState;
  groundPlane: GroundPlaneSettings;
  detectedGroundPlane?: DetectedGroundPlane;
  isTopView: boolean;
  showGrid: boolean;
  useFisheyeProjection: boolean;
  focusedAnnotationId?: string;
  focusedPosition?: Point3D;
  cameraResetCounter: number;
  clipBox: ClipBoxSettings;
}

export interface SelectionState {
  selectedAnnotationIds: string[];
  hoveredAnnotationId?: string;
  selectedPoints?: number[];
}


export interface PointCloudData {
  positions: Float32Array;
  intensities?: Float32Array;
  colors?: Float32Array;
  labels?: Uint8Array;
  pointCount: number;
}


export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface BulkOperationResponse {
  success_count: number;
  error_count: number;
  errors: Array<{ index: number; error: string }>;
}

export interface PredictionInjectionResponse {
  task_id: string;
  injected_count: number;
  source: string;
  created_annotations: string[];
}


export type QAReviewMode = 'view_only' | 'edit' | 'suggest';
export type QAReviewStatus = Schema<'QAReviewStatus'>;
export type ReviewVerdict = Schema<'ReviewVerdict'>;
export type SuggestionSeverity = 'low' | 'medium' | 'high' | 'critical';
export type SuggestionType = Schema<'SuggestionType'>;

export type QAReviewSummary = Omit<
  Schema<'QAReviewSummary'>,
  'suggestions_addressed' | 'suggestions_dismissed'
> & {
  suggestions_addressed?: number;
  suggestions_dismissed?: number;
  outcome?: 'accepted' | 'rejected' | 'no_change';
  next_stage?: 'annotation' | 'qa' | 'customer_qa' | 'accepted';
};

export type QAReview = Omit<
  NullToUndefined<Schema<'QAReviewResponse'>>,
  'summary'
> & {
  summary?: QAReviewSummary;
};

// verdict is a free string in the OpenAPI schema; keep the UI's narrow union.
export type AnnotationReview = Omit<
  NullToUndefined<Schema<'AnnotationReviewResponse'>>,
  'verdict'
> & {
  verdict?: ReviewVerdict;
};

export interface AnnotationComment
  extends Omit<
    NullToUndefined<Schema<'AnnotationCommentResponse'>>,
    'replies'
  > {
  replies: AnnotationComment[];
}

export type QASuggestion = NullToUndefined<Schema<'QASuggestionResponse'>>;

export type QATaskStats = Schema<'QATaskStats'>;

export interface GenerateSuggestionsResponse {
  task_id: string;
  suggestions_count: number;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
}


export type AnnotatorStats = Schema<'AnnotatorStats'>;

export type TaskBreakdown = Schema<'TaskBreakdown'>;

export type StageBreakdown = Schema<'StageBreakdown'>;

export type MostTimeConsumingTask = Schema<'MostTimeConsumingTask'>;

export type RecentActivity = Schema<'RecentActivity'>;

export type EfficiencyMetrics = Schema<'EfficiencyMetrics'>;

export type PMDashboardStats = Schema<'PMDashboardStats'>;
