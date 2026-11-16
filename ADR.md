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

## 4. Testing approach: business logic against a real temporary database
Date: 2026-10-02
Status: Decided
Context: The assignment requires at least 70% coverage of the core business logic of both domains. I had to decide what to test, how the tests get a database, and what counts towards the coverage number.
Decision: I test both service.py files directly with pytest, and each test gets its own new SQLite database in a temporary folder. Coverage only includes the service modules, while .coveragerc excludes routes.py.
Alternatives considered: I considered using mocks instead of a database, but rejected this because important rules depend on SQLite, such as foreign keys and CHECK constraints. I also considered mainly testing through Flask's test client, but rejected this because those tests depend on the HTML and focus more on Flask than the actual business rules.
Consequences: The tests cover validation, double bookings, status changes, and delete protection, with 100% coverage for both service modules. The routes and templates are not automatically tested, so I check the pages in the browser after making changes.

cat >> ADR.md <<'EOF'

## 5. Not building billing and invoices
Date: 2026-10-03
Status: Decided
Context: The company is paid per lesson and every tutor already has an hourly rate, so generating invoices from completed lessons was an obvious next feature. I had to decide whether it belonged in this version.
Decision: I did not build billing: there is no invoices or payments table, and the app does not calculate what a guardian owes. The tutor's hourly_rate is stored but not used in any calculation yet.
Alternatives considered: An invoices table linked to completed lessons, with amounts calculated from the tutor's hourly rate and the lesson's length. Rejected because billing would be a third domain with its own data and rules (payment status, refunds, corrections), beyond the two domains the assignment asks for, and it would take time away from tests and documentation.
Consequences: The app stays focused on customers and scheduling, which keeps it easier to test and explain. If billing is added later, it can become its own service that reads completed lessons through the lessons domain, the same way lessons read students through the customers domain.
## 6. Splitting the app into a customers service and a lessons service
Date: 2026-11-16
Status: Decided
Context: Assignment 2 requires one service per feature domain, each in its own container with its own database, calling the other over HTTP. ADR-2 drew the seam between Customer Management and Lesson Management, and in the monolith Lesson Management reached student data only through get_student and list_students in customers/service.py.
Decision: The seam stays where ADR-2 put it, so ADR-2 held. The customers service owns students and their guardians' contact details; the lessons service owns tutors and lessons. Only student data crosses the seam, read by the lessons service over HTTP: GET /students/{id} replaces get_student, to check that the student exists when a lesson is scheduled, and GET /students replaces list_students, to show names in the lesson list and the booking form with one call per page rather than one per lesson. Calls go one way only: the customers service never calls the lessons service. The staff accounts move into the customers service, because only two service containers are allowed. After login it hands out a signed token that both services check themselves with a shared secret, so checking a login never needs a call across the seam.
Alternatives considered: Copying each student's name into the lessons table was rejected, because the copy goes stale when a name is edited and would need its own syncing. Combining lessons and students in the browser for everything was rejected, because the check that a student exists before booking must happen on the server, where it cannot be skipped. Having the customers service ask the lessons service before deleting a student was rejected, because each service would then depend on the other being up.
Consequences: In Lesson Management only the two places that called customers/service.py change; they become HTTP requests with a timeout. Scheduling a lesson and showing students' names now depend on the customers service being up, while the customers service keeps working when the lessons service is down. The foreign key from lessons.student_id to students is lost, so a student who still has lessons can now be deleted; ADR-7 describes how this is compensated.
