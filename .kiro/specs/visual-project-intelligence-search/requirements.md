# Requirements Document

## Introduction

Visual Project Intelligence Search is an AI-powered image search system for NPC project teams. Project teams accumulate thousands of site images across projects, but currently have no way to search them by visual content — users rely on filenames or manual browsing. This feature introduces computer vision indexing, natural language search, automatic AI tagging, similarity search, and smart filtering so users can locate relevant images instantly.

The system is delivered in three hackathon phases across six parallel tracks (P1–P6), covering ingestion, AI labelling, embedding, vector storage, search API, and search UI.

**KPIs:**
- Reduce time to locate images by 60%
- Increase image reuse across projects by 25%
- Improve first-attempt search success rate by 40%

---

## Glossary

- **Image_Ingestion_Pipeline**: The Lambda-based pipeline triggered by S3 events that extracts metadata and stores image records in DynamoDB.
- **Rekognition_Service**: The AWS Rekognition integration that calls DetectLabels on ingested images to produce labels and confidence scores.
- **Tag_Normaliser**: The component that lowercases, deduplicates, and maps raw Rekognition labels to the canonical tag schema.
- **Embedding_Service**: The AWS Bedrock Titan Multimodal Embeddings integration that converts images and text queries into vector representations.
- **Vector_Store**: The OpenSearch Serverless (or pgvector) index that stores image embeddings, tags, and metadata for approximate nearest-neighbour (ANN) search.
- **Search_API**: The REST API that accepts search requests, invokes the Embedding_Service, queries the Vector_Store, and returns ranked image results.
- **Search_UI**: The front-end application that provides the search bar, filter panel, and image result grid.
- **Image_Record**: A DynamoDB item containing image_id, project_id, S3 path, timestamp, location, and associated tags.
- **Index_Record**: A Vector_Store document containing image_id, project_id, embedding vector, tags, date, and location.
- **NPC_Project_API**: The existing NPC back-end API that exposes project name, document count, and last-updated metadata.
- **ANN_Search**: Approximate nearest-neighbour search executed against the Vector_Store to find the top-K most similar embeddings.
- **Tag_Schema**: The canonical set of normalised tag strings used consistently across Image_Records and Index_Records.
- **CloudWatch**: AWS CloudWatch used for operational metrics and KPI instrumentation.

---

## Requirements

### Requirement 1: Image Ingestion Pipeline (P1)

**User Story:** As a project team member, I want newly uploaded project images to be automatically ingested and catalogued, so that they are available for search without any manual effort.

#### Acceptance Criteria

1. WHEN an image file is uploaded to the NPC S3 bucket, THE Image_Ingestion_Pipeline SHALL trigger within 60 seconds of the S3 event notification.
2. WHEN the Image_Ingestion_Pipeline processes an image, THE Image_Ingestion_Pipeline SHALL extract the image_id, project_id, S3 path, and upload timestamp from the S3 event and object metadata.
3. WHEN the Image_Ingestion_Pipeline extracts image metadata, THE Image_Ingestion_Pipeline SHALL store an Image_Record in DynamoDB containing image_id, project_id, S3 path, and timestamp.
4. IF the S3 object does not contain a resolvable project_id in its metadata or key prefix, THEN THE Image_Ingestion_Pipeline SHALL log an error to CloudWatch and skip further processing of that object.
5. IF the DynamoDB write fails, THEN THE Image_Ingestion_Pipeline SHALL retry the write up to 3 times with exponential backoff before logging a failure event to CloudWatch.
6. THE Image_Ingestion_Pipeline SHALL support JPEG and PNG image formats.

---

### Requirement 2: Automatic Image Tagging via AWS Rekognition (P2)

**User Story:** As a project team member, I want images to be automatically tagged with descriptive labels like "bridge", "crane", or "concrete crack", so that I can find images by content without manually adding tags.

#### Acceptance Criteria

1. WHEN an Image_Record is created in DynamoDB, THE Rekognition_Service SHALL call AWS Rekognition DetectLabels on the corresponding S3 image within 90 seconds.
2. WHEN AWS Rekognition returns labels, THE Rekognition_Service SHALL retain only labels with a confidence score of 70% or higher.
3. WHEN labels are retained, THE Tag_Normaliser SHALL convert all label strings to lowercase and remove duplicate values before storing them.
4. WHEN normalised tags are produced, THE Tag_Normaliser SHALL merge the tags into the corresponding Index_Record in the Vector_Store.
5. IF AWS Rekognition returns zero labels above the confidence threshold, THEN THE Rekognition_Service SHALL store an empty tag list in the Index_Record and log the event to CloudWatch.
6. IF the AWS Rekognition API call fails, THEN THE Rekognition_Service SHALL retry up to 3 times with exponential backoff before logging a failure event to CloudWatch.
7. THE Tag_Normaliser SHALL produce tags that conform to the Tag_Schema.

---

### Requirement 3: Bedrock Multimodal Embeddings (P3)

**User Story:** As a developer, I want images and text queries to be converted into vector embeddings using AWS Bedrock Titan Multimodal, so that semantic similarity search is possible across the image corpus.

#### Acceptance Criteria

1. WHEN an image is ingested, THE Embedding_Service SHALL generate a vector embedding for the image using the AWS Bedrock Titan Multimodal Embeddings model.
2. WHEN a natural language search query is submitted, THE Embedding_Service SHALL generate a vector embedding for the query text using the AWS Bedrock Titan Multimodal Embeddings model.
3. WHEN a similarity search image is submitted, THE Embedding_Service SHALL generate a vector embedding for the uploaded image using the AWS Bedrock Titan Multimodal Embeddings model.
4. WHEN an embedding is generated, THE Embedding_Service SHALL write the embedding vector alongside the image_id and project_id to the Vector_Store as an Index_Record.
5. IF the Bedrock API call fails, THEN THE Embedding_Service SHALL retry up to 3 times with exponential backoff before logging a failure event to CloudWatch.
6. THE Embedding_Service SHALL produce embeddings that conform to the vector dimensionality defined in the Vector_Store index schema.

---

### Requirement 4: Vector Store and Index Schema (P4)

**User Story:** As a developer, I want a provisioned vector store with a well-defined index schema, so that image embeddings and metadata can be stored and queried efficiently.

#### Acceptance Criteria

1. THE Vector_Store SHALL be provisioned as an OpenSearch Serverless collection or a pgvector-enabled PostgreSQL instance prior to the ingestion pipeline going live.
2. THE Vector_Store index SHALL contain the following fields per Index_Record: image_id, project_id, embedding vector, tags (array of strings), date, and location.
3. THE Vector_Store SHALL support ANN_Search queries that return the top-K most similar Index_Records for a given query embedding, where K is configurable between 1 and 100.
4. THE Vector_Store SHALL support pre-filtering Index_Records by project_id, date range, and location tag before executing ANN_Search.
5. WHEN an Index_Record is written, THE Vector_Store SHALL make the record available for ANN_Search within 5 seconds.
6. IF an Index_Record with a duplicate image_id is written, THEN THE Vector_Store SHALL overwrite the existing record with the new values.

---

### Requirement 5: Natural Language Image Search (P3 + P5)

**User Story:** As a project team member, I want to search for images using plain English descriptions like "foundation cracks" or "steel beam damage", so that I can find relevant images without knowing their filenames.

#### Acceptance Criteria

1. WHEN a user submits a POST /search request with a non-empty query string, THE Search_API SHALL embed the query text via the Embedding_Service and execute an ANN_Search against the Vector_Store.
2. WHEN the ANN_Search completes, THE Search_API SHALL return the top-K matching image results, where K defaults to 20 and is configurable per request up to 100.
3. WHEN results are returned, THE Search_API SHALL include image_id, project_id, S3 image URL, tags, date, and relevance score for each result.
4. WHEN a POST /search request is received, THE Search_API SHALL return a response within 3 seconds under normal operating conditions.
5. IF the query string is empty or missing, THEN THE Search_API SHALL return an HTTP 400 response with a descriptive error message.
6. IF the Vector_Store returns zero results, THEN THE Search_API SHALL return an HTTP 200 response with an empty results array and a message indicating no matches were found.
7. THE Search_API SHALL require a valid authentication token on all POST /search requests and return HTTP 401 for unauthenticated requests.

---

### Requirement 6: Similarity Search (P5)

**User Story:** As a project team member, I want to upload an image and find visually similar images across all projects, so that I can discover related site photos without needing to describe them in words.

#### Acceptance Criteria

1. WHEN a user submits a POST /search/similar request with a base64-encoded image, THE Search_API SHALL embed the image via the Embedding_Service and execute an ANN_Search against the Vector_Store.
2. WHEN the ANN_Search completes, THE Search_API SHALL return the top-K visually similar image results using the same result schema as POST /search.
3. WHEN a POST /search/similar request is received, THE Search_API SHALL return a response within 5 seconds under normal operating conditions.
4. IF the base64 image payload is missing or malformed, THEN THE Search_API SHALL return an HTTP 400 response with a descriptive error message.
5. IF the submitted image cannot be decoded to a valid JPEG or PNG, THEN THE Search_API SHALL return an HTTP 422 response with a descriptive error message.
6. THE Search_API SHALL require a valid authentication token on all POST /search/similar requests and return HTTP 401 for unauthenticated requests.

---

### Requirement 7: Smart Filters (P4 + P6)

**User Story:** As a project team member, I want to filter search results by project, date range, location, or detected object tags, so that I can narrow down large result sets to the most relevant images.

#### Acceptance Criteria

1. WHEN a POST /search request includes a filters object, THE Search_API SHALL apply the specified filters as pre-filters on the Vector_Store before executing ANN_Search.
2. THE Search_API SHALL support the following filter dimensions: project_id (exact match), date range (from/to ISO 8601 dates), location (string match against the location field), and tags (one or more tag strings from the Tag_Schema).
3. WHEN multiple filter dimensions are specified, THE Search_API SHALL apply all filters as a logical AND.
4. WHEN the Search_UI renders the filter panel, THE Search_UI SHALL display available tag options sourced from the Vector_Store index, showing the result count for each tag option.
5. WHEN the Search_UI renders the filter panel, THE Search_UI SHALL display available project options sourced from the Vector_Store index, showing the result count for each project option.
6. IF a filter value does not match any Index_Records, THEN THE Search_API SHALL return an HTTP 200 response with an empty results array.

---

### Requirement 8: Project Context Linking (P3 + P6)

**User Story:** As a project team member, I want each search result to display the project name, document count, and last-updated date, so that I can understand the context of an image without leaving the search results page.

#### Acceptance Criteria

1. WHEN the Search_API returns image results, THE Search_API SHALL enrich each result with project_name, document_count, and last_updated by calling the NPC_Project_API using the result's project_id.
2. WHEN the Search_UI renders a result card, THE Search_UI SHALL display the project_name, document_count, last_updated, image tags, and capture date for each result.
3. WHEN a user clicks a result card, THE Search_UI SHALL navigate the user to the corresponding project in the NPC application.
4. IF the NPC_Project_API returns an error for a given project_id, THEN THE Search_API SHALL include the image result with project context fields set to null and log the enrichment failure to CloudWatch.

---

### Requirement 9: Search UI — Search Bar and Result Grid (P6)

**User Story:** As a project team member, I want a clean search interface with a search bar and image result grid, so that I can quickly enter queries and visually browse matching images.

#### Acceptance Criteria

1. THE Search_UI SHALL provide a search bar that accepts free-text natural language input and submits a POST /search request on user action (button click or Enter key).
2. WHEN a search request is in progress, THE Search_UI SHALL display a loading indicator until results are returned or an error occurs.
3. WHEN results are returned, THE Search_UI SHALL render them in a responsive image grid displaying the image thumbnail, project name, tags, and capture date for each result.
4. WHEN zero results are returned, THE Search_UI SHALL display an empty state message indicating no images matched the query.
5. WHEN a search error occurs, THE Search_UI SHALL display a user-readable error message without exposing internal error details.
6. THE Search_UI SHALL provide a "Find Similar" button on each result image that submits a POST /search/similar request using the selected image and opens the results in a side drawer.

---

### Requirement 10: KPI Instrumentation (P2 — Phase 3)

**User Story:** As a product owner, I want search performance and usage metrics logged to CloudWatch, so that I can measure progress against the KPIs of reducing search time, increasing image reuse, and improving first-attempt success rate.

#### Acceptance Criteria

1. WHEN a POST /search or POST /search/similar request completes, THE Search_API SHALL log the search latency in milliseconds to CloudWatch.
2. WHEN a user selects an image result for use in another project context, THE Search_UI SHALL emit an image reuse event to CloudWatch containing the image_id and the destination project_id.
3. WHEN a user marks a search result as relevant on the first attempt, THE Search_UI SHALL emit a first-result-relevance event to CloudWatch containing the query text and the selected image_id.
4. THE Search_API SHALL log all CloudWatch metrics with a namespace of `VisualProjectIntelligenceSearch` and include the project_id dimension where applicable.

---

### Requirement 11: End-to-End Smoke Test Validation (P1 — Phase 3)

**User Story:** As a developer, I want to validate the complete ingestion-to-search pipeline with real project images, so that I can confirm the system works end-to-end before the demo.

#### Acceptance Criteria

1. WHEN 10 real project images are ingested via the Image_Ingestion_Pipeline, THE Vector_Store SHALL contain a corresponding Index_Record with a non-empty embedding vector and at least one tag for each image within 3 minutes of upload.
2. WHEN 5 natural language queries are submitted via POST /search against the ingested images, THE Search_API SHALL return at least one result with a relevance score above 0.5 for each query.
3. WHEN a POST /search/similar request is submitted using one of the ingested images, THE Search_API SHALL return at least 3 results from the ingested image set.
