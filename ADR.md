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

## 3. Linking lessons to students across the domain boundary
Date: 2026-09-30
Status: Decided
Context: Every lesson belongs to a student, but students belong to Customer Management and lessons to Lesson Management (ADR-2). I had to decide how the lessons table refers to a student inside the one shared SQLite file.
Decision: lessons.student_id keeps a foreign key to students.id, but it is the only link between the tables of the two domains, and Lesson Management code never queries the students table directly. Instead it uses customers/service.py.
Alternatives considered: I considered using student_id as a normal integer and checking in the application code whether the student exists. I chose a foreign key instead because SQLite can prevent invalid student references automatically, and I also avoided direct joins to keep Lesson Management independent from the students table structure.
Consequences: A student cannot be deleted while they still have lessons linked to them, and the application can turn the database error into a clear message. If the domains are separated into different services later, the foreign key will be replaced by a check through the Customer Management API.