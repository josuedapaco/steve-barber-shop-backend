CREATE TABLE `occupied_slots` (
	`barber_id` text NOT NULL,
	`date` text NOT NULL,
	`time` text NOT NULL,
	`appointment_id` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `slot_unique` ON `occupied_slots` (`barber_id`,`date`,`time`);
