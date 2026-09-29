## 1. Backend Framework : Flask
Date: 2026-09-29
Status: Decided
Context: A python framework was needed for a small application with a staff login and two feature domains. The app does not need advanced features such as async support or auto generated API documentation because they are made for heavier applications.
Decision: The decision was made to use Flask because it is lightweight and provides control over routing and structure.
Alternatives considered: FastAPI, but it is built around async and API development, something that this project does not need. Django was also considered, but it is designed for an application with more than two small domains.
Consequences: This choice provides a low dependency count and the codebase is easy to explain. However now I need to write routing and request validation by hand instead of having it provided by Django. 

## 2. Domain scoping: Customer Management and Lesson Management
Date: 2026-09-29
Status: Decided
Context: This assignment requires two distinct domains in the backend which both have limited dependencies and clear responsibilites. So the functionality had to be divided in two areas.
Decision: Therefore I split the application into two domains. The Customer Management shows the student information and student table and the Lesson Management shows the tutors and the lessons and their tables. 
Alternatives considered: I considered using Scheduling and Billing as the domains and an invoices table as the second domain. This idea was rejected because it would introduce a third area into the project. 
Consequences: The domains have a clear boundary because of this separation. In the case that Customer Management becomes a separate service in the future there is no need for it to depend on the Lesson Management, however Lesson Management obtains student information from Customer Management, not from the database.

## 3. Database schema: staff, students, tutors, and lessons only
Date: 2026-09-29
Status: Decided
Context: I needed to decide the database structure for the initial version. This is being done before the implementation of the core features of the business logic. 
Decision: The initial database has four tables: staff, students, tutors and lessons. It does not have an invoices or payments table yet.
Alternatives considered: I considered adding an invoices table linked to lessons so the application could also do billing. I rejected this for now because it would include a third domain as well as the two domains required for the assignment.
Consequences: Keeping this database design makes the application easier to understand, test and document. Billing is documented as a deliberate decision to not implement.