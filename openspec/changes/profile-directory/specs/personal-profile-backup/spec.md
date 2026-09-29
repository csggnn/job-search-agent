# personal-profile-backup Delta

## Purpose

Keys and personal profile data are not in git, so git cannot recover them. A backup copies
them to a folder chosen by the user, and a restore puts them back into a checkout.

## ADDED Requirements

### Requirement: Backup copies keys and the personal profile to a folder
`scripts/profile.sh backup <folder>` SHALL copy the current checkout's `.env` and every file
of its personal profile (resume, job preferences, generated state and eval set) into
`<folder>`. The default profile's generated state SHALL NOT be copied.

#### Scenario: Backup to a new folder
- **WHEN** a user runs `scripts/profile.sh backup <folder>` and `<folder>` does not exist
- **THEN** `<folder>` is created
- **AND** it contains `.env` and every personal profile file present in the checkout

### Requirement: Backup does not overwrite an unrelated folder
Backup SHALL write only to a folder that does not exist or that holds an earlier backup.
Writing to an earlier backup SHALL replace its contents.

#### Scenario: Target folder holds other files
- **WHEN** a user runs `scripts/profile.sh backup <folder>` and `<folder>` exists but holds
  no earlier backup
- **THEN** the command fails with an error naming `<folder>`
- **AND** `<folder>` is unchanged

#### Scenario: Target folder holds an earlier backup
- **WHEN** a user runs `scripts/profile.sh backup <folder>` and `<folder>` holds an earlier backup
- **THEN** `<folder>` holds only the new backup's files

### Requirement: Restore replaces keys and the personal profile with a backup
`scripts/profile.sh restore <folder>` SHALL replace the current checkout's `.env` and
personal profile with the backup's. After a restore, both SHALL equal the backup.

#### Scenario: Restore after data loss
- **WHEN** a checkout has lost `.env` and the personal profile and the user runs
  `scripts/profile.sh restore <folder>` on a backup
- **THEN** `.env` and the personal profile equal the backup
- **AND** the next pipeline run uses the personal profile

#### Scenario: Restore over newer data
- **WHEN** the personal profile holds files that the backup does not and the user runs
  `scripts/profile.sh restore <folder>`
- **THEN** those files are removed

### Requirement: Restore reads only a backup
Restore SHALL fail when `<folder>` does not hold a backup, and SHALL leave the checkout
unchanged.

#### Scenario: Folder is not a backup
- **WHEN** a user runs `scripts/profile.sh restore <folder>` on a folder that holds no backup
- **THEN** the command fails with an error naming `<folder>`
- **AND** `.env` and the personal profile are unchanged

### Requirement: The README documents backup and its limits
The README SHALL describe backup and restore. It SHALL state that `git clean -x` deletes
`.env` and the personal profile, and that a backup taken while a pipeline command runs may
hold an inconsistent database.

#### Scenario: User looks for how to protect personal data
- **WHEN** a user reads the README section on the personal profile
- **THEN** it gives the backup and restore commands
- **AND** it warns about `git clean -x` and about backing up during a running command
